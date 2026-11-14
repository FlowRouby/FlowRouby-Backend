"""FlowSpec DSL Emitter: Translates a normalized ProcessGraph into natural indentation-based FlowSpec DSL code."""

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

_SERVICE_LIKE = {NodeType.TASK, NodeType.SERVICE_TASK, NodeType.SEND_TASK, NodeType.RECEIVE_TASK}
_DSL_KEYWORDS: Dict[NodeType, str] = {
    **{node_type: "service task" for node_type in _SERVICE_LIKE},
    NodeType.USER_TASK: "user task",
    NodeType.SCRIPT_TASK: "script task",
    NodeType.MANUAL_TASK: "manual task",
    NodeType.BUSINESS_RULE_TASK: "business rule",
    NodeType.CALL_ACTIVITY: "call activity",
}
_GATEWAY_KEYWORDS: Dict[NodeType, str] = {
    NodeType.EXCLUSIVE_GATEWAY: "decision",
    NodeType.PARALLEL_GATEWAY: "parallel split",
    NodeType.INCLUSIVE_GATEWAY: "inclusive split",
}

JUEL_VAR_RE = re.compile(r"^\$\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}$")
_EXPR_TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|!=|==|&&|\|\||!')


def _to_natural_expr(raw_expr: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        tok = match.group(0)
        if tok.startswith(('"', "'")):
            return tok
        return {
            "==": " is ",
            "!=": " is not ",
            "&&": " and ",
            "||": " or ",
            "!": " not ",
        }[tok]

    return re.sub(r"\s{2,}", " ", _EXPR_TOKEN_RE.sub(_replace, raw_expr)).strip()


class FlowSpecEmitter:
    """Serializes a ProcessGraph into natural indentation-based FlowSpec DSL source code."""

    def emit(self, graph: ProcessGraph) -> str:
        lines: List[str] = []
        lines.append(f"process {self._quote(graph.name or graph.process_id)} as {graph.process_id}")

        lanes = graph.lanes
        if lanes:
            emitted_ids: Set[str] = set()
            for lane in lanes:
                lines.append(f"  lane {self._quote(lane.name or lane.id)}")
                for nid in lane.flow_node_refs:
                    node = graph.nodes.get(nid)
                    if node and graph.lane_of(nid) is lane and nid not in emitted_ids:
                        emitted_ids.add(nid)
                        for nline in self._emit_node(graph, node):
                            lines.append(f"    {nline}")

            for nid, node in graph.nodes.items():
                if nid not in emitted_ids:
                    for nline in self._emit_node(graph, node):
                        lines.append(f"  {nline}")
        else:
            for node in graph.nodes.values():
                for nline in self._emit_node(graph, node):
                    lines.append(f"  {nline}")

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
            lines = [f"start {display_name} as {node.id}"]
            start_form_ref = camunda.form_ref(node.extensions)
            start_fields = camunda.form_fields(node.extensions)
            if start_form_ref:
                lines.append(f"  use form {self._quote(start_form_ref)}")
            for ff in start_fields:
                lines.append(f"  ask {ff.field_type} {ff.id} labeled {self._quote(ff.label)}")
            if out_edges:
                lines.append(f"  next is {out_edges[0].target_ref}")
            return lines

        if isinstance(node, EndEventNode):
            return [f"end {display_name} as {node.id}"]

        if isinstance(node, GatewayNode):
            gw_keyword = _GATEWAY_KEYWORDS.get(node.node_type, "decision")
            lines = [f"{gw_keyword} {display_name} as {node.id}"]
            default_ids = self._default_edge_ids(node, out_edges)
            for edge in out_edges:
                condition = self._condition_text(edge)
                if condition:
                    lines.append(f"  if {condition} go to {edge.target_ref}")
                elif edge.id in default_ids and len(out_edges) > 1:
                    lines.append(f"  otherwise go to {edge.target_ref}")
                else:
                    lines.append(f"  branch to {edge.target_ref}")
            return lines

        task_keyword = _DSL_KEYWORDS.get(node.node_type, "service task")
        lines = [f"{task_keyword} {display_name} as {node.id}"]

        if node.node_type is NodeType.USER_TASK:
            task_form_ref = camunda.form_ref(node.extensions)
            if task_form_ref:
                lines.append(f"  use form {self._quote(task_form_ref)}")
            for ff in camunda.form_fields(node.extensions):
                lines.append(f"  ask {ff.field_type} {ff.id} labeled {self._quote(ff.label)}")

        elif node.node_type in _SERVICE_LIKE:
            delegate = camunda.delegate_class(node.extensions)
            if delegate:
                lines.append(f"  delegate {self._quote(delegate)}")
            hc = camunda.http_connector(node.extensions)
            if hc:
                lines.append("  http call")
                lines.append(f"    method {self._quote(hc.method)}")
                lines.append(f"    url {self._quote(hc.url)}")
                if hc.headers:
                    lines.append("    headers")
                    for k, v in hc.headers.items():
                        lines.append(f"      {self._quote(k)} is {self._quote(v)}")
                if hc.payload_raw:
                    payload_entries = self._extract_payload_entries(hc.payload_raw)
                    if payload_entries:
                        lines.append("    payload")
                        for entry in payload_entries:
                            lines.append(f"      {entry}")
                for out_target, out_src in hc.output_parameters.items():
                    lines.append(f"    save {out_src} as {out_target}")

        elif node.node_type is NodeType.BUSINESS_RULE_TASK:
            decision = camunda.decision_ref(node.extensions)
            if decision:
                res_var = camunda.result_variable(node.extensions) or "decision_result"
                lines.append(f"  decide {self._quote(decision)} into {res_var}")

        elif isinstance(node, CallActivityNode):
            if node.called_element:
                lines.append(f"  call {self._quote(node.called_element)}")
            in_maps, out_maps = camunda.call_activity_mappings(node.extensions)
            for in_map in in_maps:
                if not in_map.all_variables:
                    lines.append(f"  set input {in_map.target} from {in_map.source}")
            for out_map in out_maps:
                if not out_map.all_variables:
                    lines.append(f"  set output {out_map.target} from {out_map.source}")

        elif isinstance(node, ScriptTaskNode):
            script = (node.script or "").strip()
            if script:
                lines.append(f"  run script {self._quote(script)}")

        in_params, out_params = camunda.input_output_parameters(node.extensions)
        for k, v in in_params.items():
            if v:
                lines.append(f"  set input {k} from {_to_natural_expr(v)}")
        for k, v in out_params.items():
            if v:
                lines.append(f"  set output {k} from {_to_natural_expr(v)}")

        for edge in out_edges:
            lines.append(f"  next is {edge.target_ref}")

        return lines

    @staticmethod
    def _condition_text(edge: SequenceFlowEdge) -> Optional[str]:
        """The flow condition in natural FlowSpec syntax, or None when there is no usable condition."""
        if edge.condition is None:
            return None
        stripped = camunda.strip_juel(edge.condition.text)
        return _to_natural_expr(stripped) if stripped else None

    def _default_edge_ids(self, node: GatewayNode, out_edges: List[SequenceFlowEdge]) -> Set[str]:
        """Ids of the branches emitted as ``otherwise``."""
        explicit = {e.id for e in out_edges if e.is_default}
        if explicit or node.node_type not in (NodeType.EXCLUSIVE_GATEWAY, NodeType.INCLUSIVE_GATEWAY):
            return explicit
        unconditional = [e for e in out_edges if not self._condition_text(e)]
        if len(out_edges) > 1 and len(unconditional) == 1:
            return {unconditional[0].id}
        return set()

    def _extract_payload_entries(self, payload_raw: str) -> List[str]:
        """Converts a JSON-like Camunda payload string into natural FlowSpec payload entries."""
        entries: List[str] = []
        try:
            parsed = json.loads(payload_raw)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if isinstance(v, str):
                        m = JUEL_VAR_RE.match(v.strip())
                        if m:
                            entries.append(f"{self._quote(k)} from {m.group(1)}")
                        else:
                            entries.append(f"{self._quote(k)} from {self._quote(v)}")
                    elif isinstance(v, bool):
                        entries.append(f"{self._quote(k)} from {'true' if v else 'false'}")
                    elif isinstance(v, (int, float)):
                        entries.append(f"{self._quote(k)} from {v}")
                return entries
        except Exception:
            pass
        return []

    @staticmethod
    def _quote(text: str) -> str:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
