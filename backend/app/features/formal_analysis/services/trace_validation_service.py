"""Trace validation: is a user-written trace one of the executions the process model allows?

Membership is decided by the DFA inferred from the model. This service adds what the DFA does
not know: translating original BPMN ids into DFA symbols and annotating every consumed step with
the gateways crossed to reach it (a drawing aid computed on the graph, not part of the automaton).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from ...processes.intermediate_model.models import GatewayNode, ProcessGraph
from ..dfa.dfa_builder import DFA


class TraceRequestError(ValueError):
    """The trace fields of a request are missing, duplicated or malformed."""


def parse_trace_request(trace: Optional[str], bpmn_trace: Optional[str]) -> Tuple[List[str], bool]:
    """Parses the two mutually exclusive form fields.

    Returns the parsed list and whether it is expressed in BPMN ids (``True``) or DFA symbols
    (``False``). Exactly one field must be present and it must be a JSON array of strings.
    """
    if trace is not None and bpmn_trace is not None:
        raise TraceRequestError("Provide either 'trace' or 'bpmn_trace', not both.")
    if trace is None and bpmn_trace is None:
        raise TraceRequestError("Provide one of 'trace' (DFA symbols) or 'bpmn_trace' (BPMN ids).")

    field_name, raw = ("trace", trace) if trace is not None else ("bpmn_trace", bpmn_trace)
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise TraceRequestError(f"Invalid {field_name} JSON: {exc}") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise TraceRequestError(f"'{field_name}' must be a JSON array of strings.")
    return parsed, trace is None


class TraceValidationService:
    """Validates traces against a DFA and explains the walk in terms of the process graph."""

    def translate_bpmn_trace(self, bpmn_trace: List[str], bpmn_node_ids: Dict[str, str]) -> List[str]:
        """Maps original BPMN ids to DFA symbols; an id that is not in the map is kept as written."""
        symbol_by_bpmn_id = {bpmn_id: symbol for symbol, bpmn_id in bpmn_node_ids.items()}
        return [symbol_by_bpmn_id.get(item, item) for item in bpmn_trace]

    def validate_bpmn_trace(
        self, graph: ProcessGraph, dfa: DFA, bpmn_node_ids: Dict[str, str], bpmn_trace: List[str]
    ) -> Dict[str, Any]:
        return self.validate(graph, dfa, self.translate_bpmn_trace(bpmn_trace, bpmn_node_ids))

    def validate(self, graph: ProcessGraph, dfa: DFA, trace: List[str]) -> Dict[str, Any]:
        """Walks ``trace`` (DFA symbols) through the DFA and returns the validation payload."""
        walk = dfa.walk(trace).to_dict()

        consumed: Set[str] = set()
        steps: List[Dict[str, Any]] = []
        for step in walk["steps"]:
            symbol = step["symbol"]
            steps.append({**step, "via_gateways": self._gateways_crossed(graph, symbol, consumed)})
            consumed.add(symbol)

        return {
            "accepted": walk["accepted"],
            "trace": list(trace),
            "steps": steps,
            "consumed": walk["consumed"],
            "final_state": walk["final_state"],
            "rejected_at": walk["rejected_at"],
            "rejection_reason": walk["rejection_reason"],
            "expected_symbols": walk["expected_symbols"],
        }

    def _gateways_crossed(self, graph: ProcessGraph, node_id: str, consumed: Set[str]) -> List[str]:
        """Gateways on a gateway-only path from an already consumed node to ``node_id``.

        A gateway qualifies when it can be reached forward from a consumed node and can reach the
        node going forward, passing through gateways only. Sorted, so the result is deterministic.
        """
        if not consumed:
            return []
        reaching_node = self._gateways_reachable(graph, [node_id], backwards=True)
        if not reaching_node:
            return []
        reached_from_consumed = self._gateways_reachable(graph, sorted(consumed), backwards=False)
        return sorted(reaching_node & reached_from_consumed)

    def _gateways_reachable(self, graph: ProcessGraph, origins: List[str], backwards: bool) -> Set[str]:
        """Gateways reachable from ``origins`` over edges, never walking through a non-gateway node."""
        found: Set[str] = set()
        pending = list(origins)
        while pending:
            current = pending.pop()
            edges = graph.get_incoming_edges(current) if backwards else graph.get_outgoing_edges(current)
            for edge in edges:
                neighbour = edge.source_ref if backwards else edge.target_ref
                if neighbour in found or not isinstance(graph.nodes.get(neighbour), GatewayNode):
                    continue
                found.add(neighbour)
                pending.append(neighbour)
        return found
