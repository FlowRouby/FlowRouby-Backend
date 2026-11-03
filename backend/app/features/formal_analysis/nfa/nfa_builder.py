"""Epsilon-NFA (Non-Deterministic Finite Automaton) construction from a BPMN ProcessGraph.

Implements interleaving semantics with boolean flag vectors (f_1, ..., f_k) in {0,1}^k
to model ParallelGateways (AND-split/join) and InclusiveGateways (OR-split/join).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from ...processes.intermediate_model.models import (
    EndEventNode,
    FlowNode,
    GatewayDirection,
    GatewayNode,
    NodeType,
    ProcessGraph,
    StartEventNode,
)

EPSILON = "ε"
MAX_CONCURRENT_BRANCHES = 5


@dataclass
class ParallelRegionSpec:
    """Describes a matched split->join parallel or inclusive block."""
    split_id: str
    join_id: str
    gateway_type: NodeType
    branches: List[List[str]]  # Each branch is an ordered list of node IDs between split and join
    region_nodes: Set[str] = field(default_factory=set)


@dataclass
class EpsilonNFA:
    """Formal representation of an ε-NFA M = (Q, Σ, δ, q_0, F)."""
    states: Set[str] = field(default_factory=set)
    alphabet: Set[str] = field(default_factory=set)
    transitions: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)
    start_state: str = "q_init"
    accept_states: Set[str] = field(default_factory=set)
    node_to_states: Dict[str, Set[str]] = field(default_factory=dict)
    flag_regions: List[Dict[str, Any]] = field(default_factory=list)
    structural_issues: List[Dict[str, str]] = field(default_factory=list)

    def add_state(self, state: str, node_id: Optional[str] = None) -> None:
        self.states.add(state)
        self.transitions.setdefault(state, {})
        if node_id:
            self.node_to_states.setdefault(node_id, set()).add(state)

    def add_transition(self, src: str, symbol: str, dst: str) -> None:
        self.add_state(src)
        self.add_state(dst)
        if symbol != EPSILON:
            self.alphabet.add(symbol)
        self.transitions[src].setdefault(symbol, set()).add(dst)

    def epsilon_closure(self, state_set: Set[str] | FrozenSet[str]) -> FrozenSet[str]:
        stack = list(state_set)
        closure = set(state_set)
        while stack:
            current = stack.pop()
            for nxt in self.transitions.get(current, {}).get(EPSILON, set()):
                if nxt not in closure:
                    closure.add(nxt)
                    stack.append(nxt)
        return frozenset(closure)

    def to_dict(self) -> Dict[str, Any]:
        serialized_transitions = {
            src: {sym: sorted(list(dsts)) for sym, dsts in sym_map.items()}
            for src, sym_map in sorted(self.transitions.items())
            if sym_map
        }
        return {
            "states": sorted(list(self.states)),
            "alphabet": sorted(list(self.alphabet)),
            "start_state": self.start_state,
            "accept_states": sorted(list(self.accept_states)),
            "transitions": serialized_transitions,
            "flag_regions": self.flag_regions,
        }


class NFABuilder:
    """Builds an EpsilonNFA from a normalized ProcessGraph."""

    def build(self, graph: ProcessGraph) -> EpsilonNFA:
        nfa = EpsilonNFA(start_state="q_init")
        nfa.add_state("q_init")

        regions, mismatched_joins = self._detect_parallel_and_inclusive_regions(graph)
        nfa.structural_issues.extend(mismatched_joins)

        region_by_split: Dict[str, ParallelRegionSpec] = {r.split_id: r for r in regions}
        internal_region_nodes: Set[str] = set()
        for r in regions:
            internal_region_nodes.update(r.region_nodes)
            internal_region_nodes.add(r.join_id)

        # Create entry/exit states for all non-internal nodes
        for node_id, node in graph.nodes.items():
            if node_id in internal_region_nodes and node_id not in region_by_split:
                continue

            in_state = f"in:{node_id}"
            out_state = f"out:{node_id}"
            nfa.add_state(in_state, node_id=node_id)
            nfa.add_state(out_state, node_id=node_id)

            if isinstance(node, StartEventNode):
                nfa.add_transition("q_init", EPSILON, in_state)
                nfa.add_transition(in_state, node_id, out_state)
            elif isinstance(node, EndEventNode):
                nfa.add_transition(in_state, node_id, out_state)
                nfa.accept_states.add(out_state)
            elif isinstance(node, GatewayNode):
                if node_id in region_by_split:
                    self._build_flag_region(nfa, graph, region_by_split[node_id])
                elif (
                    node.node_type == NodeType.PARALLEL_GATEWAY
                    and node.direction == GatewayDirection.CONVERGING
                ):
                    # Unmatched converging ParallelGateway (e.g. fed by an ExclusiveGateway -> Deadlock!)
                    # Do NOT add an unconditional epsilon transition from in_state to out_state,
                    # because an AND-Join cannot fire when only a single exclusive path reaches it.
                    nfa.add_state(f"deadlock_wait:{node_id}", node_id=node_id)
                    nfa.add_transition(in_state, EPSILON, f"deadlock_wait:{node_id}")
                else:
                    # ExclusiveGateway or pass-through gateway uses epsilon transition
                    nfa.add_transition(in_state, EPSILON, out_state)
            else:
                # Standard task (user_task, service_task, script_task, manual_task, business_rule_task, call_activity)
                nfa.add_transition(in_state, node_id, out_state)

        # Connect edges outside internal parallel regions
        for edge in graph.edges.values():
            src = edge.source_ref
            tgt = edge.target_ref

            if src in region_by_split:
                # Handled inside _build_flag_region
                continue
            if src in internal_region_nodes:
                # Determine if src is the join_id of a region
                matching_regions = [r for r in regions if r.join_id == src]
                if matching_regions:
                    nfa.add_transition(f"out:{src}", EPSILON, f"in:{tgt}")
                continue
            if tgt in internal_region_nodes:
                continue

            nfa.add_transition(f"out:{src}", EPSILON, f"in:{tgt}")

        return nfa

    def _detect_parallel_and_inclusive_regions(
        self, graph: ProcessGraph
    ) -> Tuple[List[ParallelRegionSpec], List[Dict[str, str]]]:
        """Finds structured AND/OR split-join pairs and detects mismatched XOR->AND joins."""
        regions: List[ParallelRegionSpec] = []
        issues: List[Dict[str, str]] = []
        matched_joins: Set[str] = set()

        for node in graph.nodes.values():
            if not isinstance(node, GatewayNode):
                continue
            if node.node_type not in (NodeType.PARALLEL_GATEWAY, NodeType.INCLUSIVE_GATEWAY):
                continue
            if node.direction != GatewayDirection.DIVERGING:
                continue

            out_edges = graph.get_outgoing_edges(node.id)
            if len(out_edges) < 2 or len(out_edges) > MAX_CONCURRENT_BRANCHES:
                continue

            # Trace each outgoing branch until it hits a converging gateway of the same type
            branches: List[List[str]] = []
            candidate_join_id: Optional[str] = None
            valid_region = True

            for edge in out_edges:
                branch_nodes: List[str] = []
                curr_id = edge.target_ref
                visited_in_branch: Set[str] = set()

                while curr_id and curr_id not in visited_in_branch:
                    visited_in_branch.add(curr_id)
                    curr_node = graph.nodes.get(curr_id)
                    if curr_node is None:
                        valid_region = False
                        break
                    if (
                        isinstance(curr_node, GatewayNode)
                        and curr_node.node_type == node.node_type
                        and curr_node.direction == GatewayDirection.CONVERGING
                    ):
                        if candidate_join_id is None:
                            candidate_join_id = curr_id
                        elif candidate_join_id != curr_id:
                            valid_region = False
                        break
                    if isinstance(curr_node, GatewayNode):
                        # Nested gateways inside branch: fallback to general graph if complex
                        valid_region = False
                        break
                    branch_nodes.append(curr_id)
                    next_edges = graph.get_outgoing_edges(curr_id)
                    if len(next_edges) != 1:
                        valid_region = False
                        break
                    curr_id = next_edges[0].target_ref

                if not valid_region or candidate_join_id is None:
                    valid_region = False
                    break
                branches.append(branch_nodes)

            if valid_region and candidate_join_id:
                join_node = graph.nodes[candidate_join_id]
                if len(join_node.incoming_flows) == len(out_edges):
                    region_nodes: Set[str] = set()
                    for b in branches:
                        region_nodes.update(b)
                    regions.append(
                        ParallelRegionSpec(
                            split_id=node.id,
                            join_id=candidate_join_id,
                            gateway_type=node.node_type,
                            branches=branches,
                            region_nodes=region_nodes,
                        )
                    )
                    matched_joins.add(candidate_join_id)

        # Check for any converging ParallelGateway that was NOT matched with a valid ParallelGateway split
        for node in graph.nodes.values():
            if (
                isinstance(node, GatewayNode)
                and node.node_type == NodeType.PARALLEL_GATEWAY
                and node.direction == GatewayDirection.CONVERGING
                and node.id not in matched_joins
            ):
                issues.append(
                    {
                        "type": "GATEWAY_DEADLOCK",
                        "node_id": node.id,
                        "message": (
                            f"Converging ParallelGateway '{node.name or node.id}' ({node.id}) is not paired with a matching "
                            f"diverging ParallelGateway (possible XOR-split to AND-join synchronization deadlock)."
                        ),
                    }
                )

        return regions, issues

    def _build_flag_region(
        self, nfa: EpsilonNFA, graph: ProcessGraph, region: ParallelRegionSpec
    ) -> None:
        """Expands a Parallel or Inclusive Gateway region using flag vectors (f_0, ..., f_{k-1})."""
        k = len(region.branches)
        split_in = f"in:{region.split_id}"
        split_out = f"out:{region.split_id}"
        join_in = f"in:{region.join_id}"
        join_out = f"out:{region.join_id}"

        nfa.add_state(join_in, node_id=region.join_id)
        nfa.add_state(join_out, node_id=region.join_id)
        nfa.add_transition(split_in, EPSILON, split_out)

        if region.gateway_type == NodeType.PARALLEL_GATEWAY:
            target_masks = [tuple(1 for _ in range(k))]
        else:
            # InclusiveGateway (OR-Split): any non-empty subset of branches (2^k - 1 masks)
            target_masks = [
                mask for mask in product((0, 1), repeat=k) if any(mask)
            ]

        nfa.flag_regions.append(
            {
                "split_id": region.split_id,
                "join_id": region.join_id,
                "gateway_type": region.gateway_type.value,
                "branch_count": k,
                "branches": region.branches,
                "target_masks": ["".join(str(b) for b in m) for m in target_masks],
            }
        )

        # For each target mask M, build the product state transitions over progress vectors
        # Progress vector p = (p_0, ..., p_{k-1}) where p_i in 0..len(branch_i)
        branch_lengths = [len(b) for b in region.branches]

        for mask in target_masks:
            mask_str = "".join(str(b) for b in mask)
            ranges = [
                range(branch_lengths[i] + 1) if mask[i] == 1 else range(1)
                for i in range(k)
            ]

            init_progress = tuple(0 for _ in range(k))
            final_progress = tuple(
                branch_lengths[i] if mask[i] == 1 else 0 for i in range(k)
            )

            def state_name(prog: Tuple[int, ...], m_str: str = mask_str) -> str:
                flags_done = "".join(
                    "1" if (mask[i] == 1 and prog[i] == branch_lengths[i]) else "0"
                    for i in range(k)
                )
                steps = "_".join(str(x) for x in prog)
                return f"flag:{region.split_id}[mask={m_str},flags={flags_done},step={steps}]"

            nfa.add_transition(split_out, EPSILON, state_name(init_progress))

            for prog in product(*ranges):
                curr_state = state_name(prog)
                nfa.add_state(curr_state)

                for i in range(k):
                    if mask[i] == 1 and prog[i] < branch_lengths[i]:
                        task_id = region.branches[i][prog[i]]
                        next_prog = list(prog)
                        next_prog[i] += 1
                        nxt_state = state_name(tuple(next_prog))
                        nfa.add_state(nxt_state, node_id=task_id)
                        nfa.add_transition(curr_state, task_id, nxt_state)

            # Only when all active branches in the mask have completed (flags == mask)
            # does the AND-Join / OR-Join synchronize and transition to join_in -> join_out
            nfa.add_transition(state_name(final_progress), EPSILON, join_in)

        nfa.add_transition(join_in, EPSILON, join_out)

