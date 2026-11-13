"""Stateless Dry-Run Simulator for FlowSpec AST (evaluates paths, expressions, HTTP mocks, and DFA acceptance)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...formal_analysis.dfa.dfa_builder import DFA
from ..ast.nodes import (
    BinaryExprAST,
    ExprAST,
    GatewayAST,
    IdentifierAST,
    LiteralAST,
    NodeAST,
    ProcessAST,
    TaskNodeAST,
    UnaryExprAST,
)


@dataclass
class SimulationResult:
    completed: bool
    visited_nodes: List[str]
    step_logs: List[Dict[str, Any]]
    http_requests_simulated: List[Dict[str, Any]]
    final_context: Dict[str, Any]
    accepted_by_dfa: Optional[bool] = None
    terminated_reason: str = "END_EVENT_REACHED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "completed": self.completed,
            "terminated_reason": self.terminated_reason,
            "accepted_by_dfa": self.accepted_by_dfa,
            "visited_nodes": list(self.visited_nodes),
            "step_logs": list(self.step_logs),
            "http_requests_simulated": list(self.http_requests_simulated),
            "final_context": dict(self.final_context),
        }


class FlowSpecSimulator:
    """Executes a stateless Dry-Run simulation over a ProcessAST given an input payload."""

    def __init__(self, max_steps: int = 100) -> None:
        self.max_steps = max_steps

    def simulate(
        self,
        ast: ProcessAST,
        input_data: Optional[Dict[str, Any]] = None,
        dfa: Optional[DFA] = None,
    ) -> SimulationResult:
        context: Dict[str, Any] = dict(input_data or {})
        node_map: Dict[str, NodeAST] = {n.id: n for n in ast.all_nodes}
        incoming_counts: Dict[str, int] = {n.id: 0 for n in ast.all_nodes}
        for n in ast.all_nodes:
            for t in n.transitions:
                incoming_counts[t] = incoming_counts.get(t, 0) + 1

        start_nodes = [n for n in ast.all_nodes if n.kind == "start"]
        if not start_nodes:
            return SimulationResult(
                completed=False,
                visited_nodes=[],
                step_logs=[],
                http_requests_simulated=[],
                final_context=context,
                accepted_by_dfa=False,
                terminated_reason="NO_START_NODE",
            )

        visited_nodes: List[str] = []
        activity_trace_for_dfa: List[str] = []
        step_logs: List[Dict[str, Any]] = []
        http_requests: List[Dict[str, Any]] = []

        ready_queue: List[str] = [start_nodes[0].id]
        join_arrivals: Dict[str, int] = {}
        steps = 0
        reached_end = False

        while ready_queue and steps < self.max_steps:
            curr_id = ready_queue.pop(0)
            node = node_map.get(curr_id)
            if node is None:
                continue

            steps += 1
            visited_nodes.append(node.id)

            if node.kind == "end":
                activity_trace_for_dfa.append(node.id)
                step_logs.append(
                    {
                        "step": steps,
                        "node_id": node.id,
                        "name": node.name,
                        "kind": node.kind,
                        "action": "Reached EndEvent",
                    }
                )
                reached_end = True
                break

            if isinstance(node, GatewayAST):
                selected_targets = self._evaluate_gateway(node, context, incoming_counts, join_arrivals)
                step_logs.append(
                    {
                        "step": steps,
                        "node_id": node.id,
                        "name": node.name,
                        "kind": node.kind,
                        "selected_targets": selected_targets,
                    }
                )
                ready_queue.extend(selected_targets)
                continue

            activity_trace_for_dfa.append(node.id)
            changes: Dict[str, Any] = {}

            if isinstance(node, TaskNodeAST):
                for ff in node.form_fields:
                    if ff.name not in context:
                        context[ff.name] = self._default_for_type(ff.field_type)
                        changes[ff.name] = context[ff.name]

                if node.http_connector:
                    hc = node.http_connector
                    rendered_payload = {
                        k: self.eval_expr(v, context) for k, v in hc.payload_fields.items()
                    }
                    mock_resp = context.get("response", {"status": 200, "id": f"MOCK-{node.id}"})
                    http_req = {
                        "node_id": node.id,
                        "method": hc.method,
                        "url": hc.url,
                        "headers": hc.headers,
                        "payload": rendered_payload,
                        "mock_response": mock_resp,
                    }
                    http_requests.append(http_req)
                    if hc.output_target:
                        if hc.output_target not in context:
                            context[hc.output_target] = mock_resp
                        changes[hc.output_target] = context[hc.output_target]

                if node.decision_ref and node.result_variable:
                    if node.result_variable not in context:
                        context[node.result_variable] = 100
                    changes[node.result_variable] = context[node.result_variable]

                for mapping in node.io_mappings:
                    val = self.eval_expr(mapping.expr, context)
                    if mapping.direction == "output":
                        context[mapping.target] = val
                        changes[mapping.target] = val

            step_logs.append(
                {
                    "step": steps,
                    "node_id": node.id,
                    "name": node.name,
                    "kind": node.kind,
                    "context_updates": changes,
                }
            )
            ready_queue.extend(node.transitions)

        dfa_accepted: Optional[bool] = None
        if dfa is not None:
            dfa_accepted = dfa.accepts(activity_trace_for_dfa)

        reason = "END_EVENT_REACHED" if reached_end else (
            "MAX_STEPS_EXCEEDED" if steps >= self.max_steps else "DEADLOCK_OR_NO_TRANSITION"
        )

        return SimulationResult(
            completed=reached_end,
            visited_nodes=visited_nodes,
            step_logs=step_logs,
            http_requests_simulated=http_requests,
            final_context=context,
            accepted_by_dfa=dfa_accepted,
            terminated_reason=reason,
        )

    def _evaluate_gateway(
        self,
        gw: GatewayAST,
        context: Dict[str, Any],
        incoming_counts: Dict[str, int],
        join_arrivals: Dict[str, int],
    ) -> List[str]:
        if gw.kind == "parallel_gateway":
            expected_in = incoming_counts.get(gw.id, 1)
            if expected_in > 1 and len(gw.branches) <= 1:
                join_arrivals[gw.id] = join_arrivals.get(gw.id, 0) + 1
                if join_arrivals[gw.id] < expected_in:
                    return []
                join_arrivals[gw.id] = 0
            return [b.target_id for b in gw.branches]

        if gw.kind == "inclusive_gateway":
            matched: List[str] = []
            default_target: Optional[str] = None
            for b in gw.branches:
                if b.branch_kind == "when" and b.condition is not None:
                    if bool(self.eval_expr(b.condition, context)):
                        matched.append(b.target_id)
                elif b.branch_kind == "default":
                    default_target = b.target_id
                else:
                    matched.append(b.target_id)
            if not matched and default_target:
                return [default_target]
            return matched

        default_target = None
        unconditional_targets: List[str] = []
        for b in gw.branches:
            if b.branch_kind == "when" and b.condition is not None:
                if bool(self.eval_expr(b.condition, context)):
                    return [b.target_id]
            elif b.branch_kind == "default":
                default_target = b.target_id
            else:
                unconditional_targets.append(b.target_id)

        if default_target:
            return [default_target]
        if unconditional_targets:
            return [unconditional_targets[0]]
        return []

    def eval_expr(self, expr: ExprAST, context: Dict[str, Any]) -> Any:
        if isinstance(expr, LiteralAST):
            return expr.value
        if isinstance(expr, IdentifierAST):
            return context.get(expr.name, 0)
        if isinstance(expr, UnaryExprAST):
            val = self.eval_expr(expr.operand, context)
            if expr.operator == "!":
                return not bool(val)
            if expr.operator == "-":
                return -(val if isinstance(val, (int, float)) else 0)
        if isinstance(expr, BinaryExprAST):
            left = self.eval_expr(expr.left, context)
            right = self.eval_expr(expr.right, context)
            op = expr.operator
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == "&&":
                return bool(left) and bool(right)
            if op == "||":
                return bool(left) or bool(right)
            l_num = left if isinstance(left, (int, float)) and not isinstance(left, bool) else 0
            r_num = right if isinstance(right, (int, float)) and not isinstance(right, bool) else 0
            if op == "<":
                return l_num < r_num
            if op == "<=":
                return l_num <= r_num
            if op == ">":
                return l_num > r_num
            if op == ">=":
                return l_num >= r_num
            if op == "+":
                return l_num + r_num
            if op == "-":
                return l_num - r_num
            if op == "*":
                return l_num * r_num
            if op == "/":
                return l_num / r_num if r_num != 0 else 0
        return None

    @staticmethod
    def _default_for_type(field_type: str) -> Any:
        ft = field_type.lower()
        if ft in ("boolean", "bool"):
            return True
        if ft in ("long", "integer", "int", "number", "double"):
            return 100
        return ""

