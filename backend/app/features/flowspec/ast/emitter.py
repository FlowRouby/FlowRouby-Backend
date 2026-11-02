"""FlowSpec DSL Emitter: Translates a normalized ProcessGraph into FlowSpec DSL code.

The IR is vendor neutral, so Camunda-specific data (forms, connectors, mappings) is read through
the temporary compatibility adapter in ``camunda_extensions``. The emitter also applies the
FlowSpec-side conventions that the IR deliberately does not carry: display-name fallbacks,
DSL keywords per task type and the implicit default branch of a gateway.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set

from ...processes.intermediate_model.models import (
    CallActivityNode,
    EndEventNode,
    FlowNode,
    GatewayNode,
    NodeType,
    ProcessGraph,
    ScriptTaskNode,
    SequenceFlowEdge,
    StartEventNode,
)
from . import camunda_extensions as camunda

# Generic BPMN tasks are emitted with the same DSL keyword as service tasks, as they always were.
_SERVICE_LIKE = {NodeType.TASK, NodeType.SERVICE_TASK, NodeType.SEND_TASK, NodeType.RECEIVE_TASK}
_DSL_KEYWORDS: Dict[NodeType, str] = {node_type: "service_task" for node_type in _SERVICE_LIKE}

JUEL_VAR_RE = re.compile(r"^\$\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}$")


class FlowSpecEmitter:
    """Serializes a ProcessGraph into clean, human-readable FlowSpec DSL source code."""

    def emit(self, graph: ProcessGraph) -> str:
        lines: List[str] = []
        lines.append(f'process {graph.process_id} {self._quote(graph.name or graph.process_id)} {{')

        lanes = graph.lanes
        if lanes:
            emitted_ids: Set[str] = set()
            for lane in lanes:
                lines.append(f"  lane {self._quote(lane.name or lane.id)} {{")
                for nid in lane.flow_node_refs:
                    node = graph.nodes.get(nid)
                    if node and graph.lane_of(nid) is lane and nid not in emitted_ids:
                        emitted_ids.add(nid)
                        for nline in self._emit_node(graph, node):
                            lines.append(f"    {nline}")
                lines.append("  }")

            # Emit any nodes that were not listed inside a lane
            for nid, node in graph.nodes.items():
                if nid not in emitted_ids:
                    for nline in self._emit_node(graph, node):
                        lines.append(f"  {nline}")
        else:
            for node in graph.nodes.values():
                for nline in self._emit_node(graph, node):
                    lines.append(f"  {nline}")

        lines.append("}")
        return "\n".join(lines) + "\n"

    def _emit_node(self, graph: ProcessGraph, node: FlowNode) -> List[str]:
        if node.node_type is NodeType.UNSUPPORTED:
            raise ValueError(
                f"Cannot emit FlowSpec for unsupported element '{node.id}' ({node.bpmn_type}); "
                "analysis must be blocked before emitting."
            )
        out_edges = graph.get_outgoing_edges(node.id)
        display_name = self._quote(node.name or node.id)

        if isinstance(node, StartEventNode):
            target_part = f" -> {out_edges[0].target_ref}" if out_edges else ""
            start_form_ref = camunda.form_ref(node.extensions)
            start_fields = camunda.form_fields(node.extensions)
            if not start_form_ref and not start_fields:
                return [f"start {node.id} {display_name}{target_part};"]
            lines = [f"start {node.id} {display_name} {{"]
            if start_form_ref:
                lines.append(f"  form_ref {self._quote(start_form_ref)};")
            for ff in start_fields:
                lines.append(f"  form_field {ff.id}: {ff.field_type} {self._quote(ff.label)};")
            if out_edges:
                lines.append(f"  -> {out_edges[0].target_ref};")
            lines.append("}")
            return lines

        if isinstance(node, EndEventNode):
            return [f"end {node.id} {display_name};"]

        if isinstance(node, GatewayNode):
            gw_keyword = node.node_type.value  # exclusive_gateway, parallel_gateway, inclusive_gateway
            lines = [f"{gw_keyword} {node.id} {display_name} {{"]
            default_ids = self._default_edge_ids(node, out_edges)
            for edge in out_edges:
                condition = self._condition_text(edge)
                if condition:
                    lines.append(f"  when ({condition}) -> {edge.target_ref};")
                elif edge.id in default_ids and len(out_edges) > 1:
                    lines.append(f"  default -> {edge.target_ref};")
                else:
                    lines.append(f"  branch -> {edge.target_ref};")
            lines.append("}")
            return lines

        # Task nodes
        task_keyword = _DSL_KEYWORDS.get(node.node_type, node.node_type.value)
        lines = [f"{task_keyword} {node.id} {display_name} {{"]

        if node.node_type is NodeType.USER_TASK:
            task_form_ref = camunda.form_ref(node.extensions)
            if task_form_ref:
                lines.append(f"  form_ref {self._quote(task_form_ref)};")
            for ff in camunda.form_fields(node.extensions):
                lines.append(f"  form_field {ff.id}: {ff.field_type} {self._quote(ff.label)};")

        elif node.node_type in _SERVICE_LIKE:
            delegate = camunda.delegate_class(node.extensions)
            if delegate:
                lines.append(f"  delegate_class {self._quote(delegate)};")
            hc = camunda.http_connector(node.extensions)
            if hc:
                lines.append("  http_connector {")
                lines.append(f"    method: {self._quote(hc.method)};")
                lines.append(f"    url: {self._quote(hc.url)};")
                if hc.headers:
                    hdr_items = ", ".join(
                        f"{self._quote(k)}: {self._quote(v)}" for k, v in hc.headers.items()
                    )
                    lines.append(f"    headers: {{ {hdr_items} }};")
                if hc.payload_raw:
                    payload_entries = self._extract_payload_entries(hc.payload_raw)
                    if payload_entries:
                        lines.append(f"    payload: {{ {', '.join(payload_entries)} }};")
                for out_target, out_src in hc.output_parameters.items():
                    lines.append(f"    output: {out_target} <- {out_src};")
                lines.append("  }")

        elif node.node_type is NodeType.BUSINESS_RULE_TASK:
            decision = camunda.decision_ref(node.extensions)
            if decision:
                res_var = camunda.result_variable(node.extensions) or "decision_result"
                lines.append(f"  decision_ref {self._quote(decision)} -> {res_var};")

        elif isinstance(node, CallActivityNode):
            if node.called_element:
                lines.append(f"  called_element {self._quote(node.called_element)};")
            in_maps, out_maps = camunda.call_activity_mappings(node.extensions)
            for in_map in in_maps:
                if not in_map.all_variables:
                    lines.append(f"  input {in_map.target} <- {in_map.source};")
            for out_map in out_maps:
                if not out_map.all_variables:
                    lines.append(f"  output {out_map.target} <- {out_map.source};")

        elif isinstance(node, ScriptTaskNode):
            script = (node.script or "").strip()
            if script:
                lines.append(f"  script {self._quote(script)};")

        # Direct input/output parameters on node
        in_params, out_params = camunda.input_output_parameters(node.extensions)
        for k, v in in_params.items():
            if v:
                lines.append(f"  input {k} <- {v};")
        for k, v in out_params.items():
            if v:
                lines.append(f"  output {k} <- {v};")

        for edge in out_edges:
            lines.append(f"  -> {edge.target_ref};")

        lines.append("}")
        return lines

    @staticmethod
    def _condition_text(edge: SequenceFlowEdge) -> Optional[str]:
        """The flow condition without its JUEL wrapper, or None when there is no usable condition."""
        if edge.condition is None:
            return None
        return camunda.strip_juel(edge.condition.text) or None

    def _default_edge_ids(self, node: GatewayNode, out_edges: List[SequenceFlowEdge]) -> Set[str]:
        """Ids of the branches emitted as ``default``.

        Explicit ``default`` flows come from the IR. For exclusive and inclusive gateways with no
        explicit default, a single unconditional branch is treated as the default, as the emitter
        always did; the IR itself does not make that inference.
        """
        explicit = {e.id for e in out_edges if e.is_default}
        if explicit or node.node_type not in (NodeType.EXCLUSIVE_GATEWAY, NodeType.INCLUSIVE_GATEWAY):
            return explicit
        unconditional = [e for e in out_edges if not self._condition_text(e)]
        if len(out_edges) > 1 and len(unconditional) == 1:
            return {unconditional[0].id}
        return set()

    def _extract_payload_entries(self, payload_raw: str) -> List[str]:
        """Converts a JSON-like Camunda payload string into FlowSpec map entries."""
        entries: List[str] = []
        try:
            parsed = json.loads(payload_raw)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if isinstance(v, str):
                        m = JUEL_VAR_RE.match(v.strip())
                        if m:
                            entries.append(f"{self._quote(k)}: {m.group(1)}")
                        else:
                            entries.append(f"{self._quote(k)}: {self._quote(v)}")
                    elif isinstance(v, bool):
                        entries.append(f"{self._quote(k)}: {'true' if v else 'false'}")
                    elif isinstance(v, (int, float)):
                        entries.append(f"{self._quote(k)}: {v}")
                return entries
        except Exception:
            pass
        return []

    @staticmethod
    def _quote(text: str) -> str:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
