"""Formal Analysis Service: orchestrates ε-NFA, DFA, Regular Expression synthesis,
and static verification of Dead Nodes, Gateway Deadlocks, and Infinite Loops."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from ...processes.intermediate_model.models import ProcessGraph
from ..dfa.dfa_builder import DFA, DFABuilder
from ..nfa.nfa_builder import EpsilonNFA, NFABuilder
from ..regular_expressions.regex_synthesizer import RegexSynthesizer


@dataclass
class FormalAnalysisReport:
    is_valid_workflow: bool
    regular_expression: str
    nfa_summary: Dict[str, Any]
    dfa: DFA
    acyclic_paths: List[List[str]]
    unreachable_nodes: List[str] = field(default_factory=list)
    deadlocks: List[Dict[str, str]] = field(default_factory=list)
    infinite_loops: List[Dict[str, Any]] = field(default_factory=list)
    valid_loops: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chomsky_classification": "Type-3 (Regular Language over Activity Traces)",
            "is_valid_workflow": self.is_valid_workflow,
            "regular_expression": self.regular_expression,
            "nfa_state_count": len(self.nfa_summary.get("states", [])),
            "dfa": self.dfa.to_dict(),
            "flag_regions": self.nfa_summary.get("flag_regions", []),
            "acyclic_paths": self.acyclic_paths,
            "diagnostics": {
                "unreachable_nodes": self.unreachable_nodes,
                "deadlocks": self.deadlocks,
                "infinite_loops": self.infinite_loops,
                "valid_loops": self.valid_loops,
            },
        }


class FormalAnalysisService:
    """Runs formal automata verification and synthesis on a ProcessGraph."""

    def __init__(self) -> None:
        self.nfa_builder = NFABuilder()
        self.dfa_builder = DFABuilder()
        self.regex_synthesizer = RegexSynthesizer()

    def analyze(self, graph: ProcessGraph) -> FormalAnalysisReport:
        nfa: EpsilonNFA = self.nfa_builder.build(graph)
        dfa: DFA = self.dfa_builder.build(nfa)
        regex = self.regex_synthesizer.synthesize(dfa)
        acyclic_paths = self.regex_synthesizer.enumerate_acyclic_paths(dfa)

        # 1. Detect unreachable BPMN nodes (Dead Nodes)
        unreachable_nodes = self._find_unreachable_nodes(graph, dfa)

        # 2. Detect Gateway Deadlocks and states that cannot reach any accepting EndEvent
        deadlocks = list(nfa.structural_issues)
        states_reaching_accept = self._find_states_reaching_accept(dfa)

        # 3. Analyze cycles (Tarjan's Strongly Connected Components on DFA)
        infinite_loops, valid_loops = self._analyze_cycles(dfa, states_reaching_accept)

        # Check if any non-accepting DFA state has 0 outgoing transitions (Deadlock state)
        for state in dfa.states:
            if state not in dfa.accept_states and not dfa.transitions.get(state):
                subset_info = dfa.state_subsets.get(state, [])
                deadlocks.append(
                    {
                        "type": "DEADLOCK_STATE",
                        "dfa_state": state,
                        "message": f"DFA state '{state}' ({subset_info}) has no outgoing transitions and is not an EndEvent.",
                    }
                )

        is_valid = (
            len(dfa.accept_states) > 0
            and len(unreachable_nodes) == 0
            and len(deadlocks) == 0
            and len(infinite_loops) == 0
        )

        return FormalAnalysisReport(
            is_valid_workflow=is_valid,
            regular_expression=regex,
            nfa_summary=nfa.to_dict(),
            dfa=dfa,
            acyclic_paths=acyclic_paths,
            unreachable_nodes=unreachable_nodes,
            deadlocks=deadlocks,
            infinite_loops=infinite_loops,
            valid_loops=valid_loops,
        )

    def _find_unreachable_nodes(self, graph: ProcessGraph, dfa: DFA) -> List[str]:
        """Checks both graph reachability from StartEvent and alphabet transitions in DFA."""
        reachable_in_graph: Set[str] = set()
        queue: deque[str] = deque(n.id for n in graph.start_nodes)
        while queue:
            curr = queue.popleft()
            if curr in reachable_in_graph:
                continue
            reachable_in_graph.add(curr)
            for edge in graph.get_outgoing_edges(curr):
                if edge.target_ref not in reachable_in_graph:
                    queue.append(edge.target_ref)

        # Also check which task/event symbols actually appear in reachable DFA transitions
        used_symbols: Set[str] = set()
        for trans in dfa.transitions.values():
            used_symbols.update(trans.keys())

        unreachable: List[str] = []
        for node_id, node in graph.nodes.items():
            if node_id not in reachable_in_graph:
                unreachable.append(node_id)
            elif node.node_type.value not in ("exclusive_gateway", "parallel_gateway", "inclusive_gateway"):
                if node_id not in used_symbols:
                    unreachable.append(node_id)
        return sorted(list(set(unreachable)))

    def _find_states_reaching_accept(self, dfa: DFA) -> Set[str]:
        """Reverse BFS from accept_states to find all DFA states that can reach completion."""
        reverse_adj: Dict[str, Set[str]] = {s: set() for s in dfa.states}
        for src, trans in dfa.transitions.items():
            for dst in trans.values():
                reverse_adj.setdefault(dst, set()).add(src)

        can_reach: Set[str] = set(dfa.accept_states)
        queue: deque[str] = deque(dfa.accept_states)
        while queue:
            curr = queue.popleft()
            for prev in reverse_adj.get(curr, set()):
                if prev not in can_reach:
                    can_reach.add(prev)
                    queue.append(prev)
        return can_reach

    def _analyze_cycles(
        self, dfa: DFA, states_reaching_accept: Set[str]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Uses Tarjan's SCC algorithm to distinguish valid retry loops from infinite trap loops."""
        index = 0
        indices: Dict[str, int] = {}
        lowlink: Dict[str, int] = {}
        stack: List[str] = []
        on_stack: Set[str] = set()
        sccs: List[List[str]] = []

        def strongconnect(v: str) -> None:
            nonlocal index
            indices[v] = index
            lowlink[v] = index
            index += 1
            stack.append(v)
            on_stack.add(v)

            for w in dfa.transitions.get(v, {}).values():
                if w not in indices:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])

            if lowlink[v] == indices[v]:
                scc: List[str] = []
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc.append(w)
                    if w == v:
                        break
                sccs.append(scc)

        for s in dfa.states:
            if s not in indices:
                strongconnect(s)

        infinite_loops: List[Dict[str, Any]] = []
        valid_loops: List[Dict[str, Any]] = []

        for scc in sccs:
            has_self_loop = len(scc) == 1 and scc[0] in dfa.transitions.get(scc[0], {}).values()
            if len(scc) > 1 or has_self_loop:
                # Collect involved symbols in this cycle
                scc_set = set(scc)
                cycle_symbols: List[str] = []
                for s in scc:
                    for sym, nxt in dfa.transitions.get(s, {}).items():
                        if nxt in scc_set:
                            cycle_symbols.append(sym)

                if any(s in states_reaching_accept for s in scc):
                    valid_loops.append(
                        {
                            "type": "VALID_LOOP",
                            "dfa_states": sorted(scc),
                            "activities": sorted(list(set(cycle_symbols))),
                            "message": "Controlled loop with valid exit path towards an EndEvent.",
                        }
                    )
                else:
                    infinite_loops.append(
                        {
                            "type": "INFINITE_LOOP_TRAP",
                            "dfa_states": sorted(scc),
                            "activities": sorted(list(set(cycle_symbols))),
                            "message": "Infinite loop trap detected: cycle has no exit path to any EndEvent.",
                        }
                    )

        return infinite_loops, valid_loops

