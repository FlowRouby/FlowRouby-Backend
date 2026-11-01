"""FlowSpec DSL Emitter: Translates a normalized ProcessGraph into FlowSpec DSL code."""

from __future__ import annotations

import json
import re
from typing import List

from ...processes.intermediate_model.models import (
    BusinessRuleTaskNode,
    CallActivityNode,
    EndEventNode,
    FlowNode,
    GatewayNode,
    NodeType,
    ProcessGraph,
    ScriptTaskNode,
    ServiceTaskNode,
    StartEventNode,
    UserTaskNode,
)

JUEL_VAR_RE = re.compile(r"^\$\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}$")


class FlowSpecEmitter:
    """Serializes a ProcessGraph into clean, human-readable FlowSpec DSL source code."""

    def emit(self, graph: ProcessGraph) -> str:
        lines: List[str] = []
        lines.append(f'process {graph.process_id} {self._quote(graph.name)} {{')

        if graph.lanes:
            emitted_ids = set()
            for lane in graph.lanes:
                lines.append(f"  lane {self._quote(lane.name)} {{")
                for nid in lane.node_ids:
                    node = graph.nodes.get(nid)
                    if node:
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
        out_edges = graph.get_outgoing_edges(node.id)

        if isinstance(node, StartEventNode):
            target_part = f" -> {out_edges[0].target_ref}" if out_edges else ""
            if not node.form_ref and not node.form_fields:
                return [f"start {node.id} {self._quote(node.name)}{target_part};"]
            lines = [f"start {node.id} {self._quote(node.name)} {{"]
            if node.form_ref:
                lines.append(f"  form_ref {self._quote(node.form_ref)};")
            for ff in node.form_fields:
                lines.append(f"  form_field {ff.id}: {ff.field_type} {self._quote(ff.label)};")
            if out_edges:
                lines.append(f"  -> {out_edges[0].target_ref};")
            lines.append("}")
            return lines

        if isinstance(node, EndEventNode):
            return [f"end {node.id} {self._quote(node.name)};"]

        if isinstance(node, GatewayNode):
            gw_keyword = node.node_type.value  # exclusive_gateway, parallel_gateway, inclusive_gateway
            lines = [f"{gw_keyword} {node.id} {self._quote(node.name)} {{"]
            for edge in out_edges:
                if edge.condition_expression:
                    lines.append(f"  when ({edge.condition_expression}) -> {edge.target_ref};")
                elif edge.is_default and node.node_type in (
                    NodeType.EXCLUSIVE_GATEWAY,
                    NodeType.INCLUSIVE_GATEWAY,
                ) and len(out_edges) > 1:
                    lines.append(f"  default -> {edge.target_ref};")
                else:
                    lines.append(f"  branch -> {edge.target_ref};")
            lines.append("}")
            return lines

        # Task nodes
        task_keyword = node.node_type.value
        lines = [f"{task_keyword} {node.id} {self._quote(node.name)} {{"]

        if isinstance(node, UserTaskNode):
            if node.form_ref:
                lines.append(f"  form_ref {self._quote(node.form_ref)};")
            for ff in node.form_fields:
                lines.append(f"  form_field {ff.id}: {ff.field_type} {self._quote(ff.label)};")

        elif isinstance(node, ServiceTaskNode):
            if node.delegate_class:
                lines.append(f"  delegate_class {self._quote(node.delegate_class)};")
            if node.http_connector:
                hc = node.http_connector
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

        elif isinstance(node, BusinessRuleTaskNode):
            if node.decision_ref:
                res_var = node.result_variable or "decision_result"
                lines.append(f"  decision_ref {self._quote(node.decision_ref)} -> {res_var};")

        elif isinstance(node, CallActivityNode):
            if node.called_element:
                lines.append(f"  called_element {self._quote(node.called_element)};")
            for in_map in node.in_mappings:
                if not in_map.all_variables:
                    lines.append(f"  input {in_map.target} <- {in_map.source};")
            for out_map in node.out_mappings:
                if not out_map.all_variables:
                    lines.append(f"  output {out_map.target} <- {out_map.source};")

        elif isinstance(node, ScriptTaskNode):
            if node.script:
                lines.append(f"  script {self._quote(node.script)};")

        # Direct input/output parameters on node
        for k, v in node.input_parameters.items():
            if v:
                lines.append(f"  input {k} <- {v};")
        for k, v in node.output_parameters.items():
            if v:
                lines.append(f"  output {k} <- {v};")

        for edge in out_edges:
            lines.append(f"  -> {edge.target_ref};")

        lines.append("}")
        return lines

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

