"""Syntax-directed translation of AST nodes to the Ruby workflow class.

Each node of the process AST becomes one Ruby method of the workflow class. While translating
tasks, the builder also collects the supporting files each node needs (form objects, HTTP jobs,
service and decision stubs) and the names of HTTP jobs that run asynchronously.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from ...flowspec.ast.nodes import GatewayAST, NodeAST, TaskNodeAST
from . import artifacts
from .expression_transpiler import RubyExpressionTranspiler
from .naming import to_pascal_case, unique_snake


class WorkflowBuilder:
    """Translates the nodes of one process into Ruby methods and collects their artifacts."""

    def __init__(
        self,
        transpiler: RubyExpressionTranspiler,
        incoming_counts: Dict[str, int],
        variable_symbols: Dict[str, Any],
    ) -> None:
        self.transpiler = transpiler
        self.incoming_counts = incoming_counts
        self.variable_symbols = variable_symbols
        self.form_objects: Dict[str, str] = {}
        self.sidekiq_jobs: Dict[str, str] = {}
        self.service_stubs: Dict[str, str] = {}
        self.decision_stubs: Dict[str, str] = {}
        self.async_http_jobs: List[str] = []
        self._used_forms: Set[str] = set()
        self._used_jobs: Set[str] = set()
        self._used_services: Set[str] = set()
        self._used_decisions: Set[str] = set()

    def build_node_method(self, node: NodeAST, method_name: str) -> str:
        lines: List[str] = [f"    # [{node.kind}] {node.name} ({node.id})"]
        lines.append(f"    def {method_name}")

        if node.kind == "end":
            lines.append("      []")
            lines.append("    end")
            return "\n".join(lines)

        if isinstance(node, GatewayAST):
            lines.extend(self._gateway_body(node))
            lines.append("    end")
            return "\n".join(lines)

        if isinstance(node, TaskNodeAST):
            lines.extend(self._task_body(node))

        targets_ruby = ", ".join(f":{t}" for t in node.transitions)
        lines.append(f"      [{targets_ruby}]")
        lines.append("    end")
        return "\n".join(lines)

    def _task_body(self, node: TaskNodeAST) -> List[str]:
        lines: List[str] = []

        if node.kind == "user_task" and (node.form_fields or node.form_ref):
            base = unique_snake(node.form_ref or node.name, node.id, self._used_forms)
            form_cls = f"{to_pascal_case(base)}Form"
            self.form_objects[f"app/forms/{base}_form.rb"] = artifacts.build_form_object(node, form_cls)
            field_symbols = ", ".join(f":{ff.name}" for ff in node.form_fields)
            lines.append(f"      form = Forms::{form_cls}.new(@context.slice({field_symbols}))")
            lines.append("      form.validate!")

        if node.http_connector:
            base = unique_snake(node.name, node.id, self._used_jobs)
            job_cls = f"{to_pascal_case(base)}HttpJob"
            self.sidekiq_jobs[f"app/jobs/{base}_http_job.rb"] = artifacts.build_http_job(node, job_cls, self.transpiler)
            out_var = node.http_connector.output_target
            sym = self.variable_symbols.get(out_var) if out_var else None
            output_is_used = bool(sym and getattr(sym, "used_in", []))
            if output_is_used:
                lines.append(f"      @context = Jobs::{job_cls}.new.perform(@context)")
            else:
                lines.append(f"      jid = Jobs::{job_cls}.perform_async(@context.transform_keys(&:to_s))")
                lines.append(
                    f'      @enqueued_jobs << {{ node_id: "{node.id}", job_class: "Jobs::{job_cls}", jid: jid }}'
                )
                self.async_http_jobs.append(job_cls)

        if node.delegate_class:
            short_cls = node.delegate_class.split(".")[-1]
            base = unique_snake(short_cls, node.id, self._used_services)
            service_cls = f"{to_pascal_case(base)}Service"
            self.service_stubs[f"app/services/{base}_service.rb"] = artifacts.build_service_stub(node, service_cls)
            lines.append(f"      @context = Services::{service_cls}.call(@context)")

        if node.decision_ref:
            base = unique_snake(node.decision_ref, node.id, self._used_decisions)
            decision_cls = f"{to_pascal_case(base)}DecisionService"
            result_var = node.result_variable or "decision_result"
            self.decision_stubs[f"app/services/decisions/{base}_decision_service.rb"] = artifacts.build_decision_stub(
                node, decision_cls, result_var
            )
            lines.append(f"      @context[:{result_var}] = Services::Decisions::{decision_cls}.evaluate(@context)")

        if node.called_element:
            sub_workflow_cls = f"{to_pascal_case(node.called_element)}Workflow"
            lines.append(f"      sub_result = Workflows::{sub_workflow_cls}.call(@context)")
            lines.append("      @context.merge!(sub_result[:context]) if sub_result.is_a?(Hash) && sub_result[:context]")

        for mapping in node.io_mappings:
            if mapping.direction == "output":
                ruby_expr = self.transpiler.transpile(mapping.expr, context_var="@context")
                lines.append(f"      @context[:{mapping.target}] = {ruby_expr}")

        return lines

    def _gateway_body(self, gw: GatewayAST) -> List[str]:
        lines: List[str] = []
        if gw.kind == "parallel_gateway":
            expected_in = self.incoming_counts.get(gw.id, 1)
            targets_ruby = ", ".join(f":{b.target_id}" for b in gw.branches)
            if expected_in > 1 and len(gw.branches) <= 1:
                lines.append(f"      @join_arrivals[:{gw.id}] += 1")
                lines.append(f"      return [] if @join_arrivals[:{gw.id}] < {expected_in}")
                lines.append(f"      @join_arrivals[:{gw.id}] = 0")
            lines.append(f"      [{targets_ruby}]")
            return lines

        if gw.kind == "inclusive_gateway":
            lines.append("      active_branches = []")
            default_target = None
            for b in gw.branches:
                if b.branch_kind == "when" and b.condition is not None:
                    cond_rb = self.transpiler.transpile(b.condition, context_var="@context")
                    lines.append(f"      active_branches << :{b.target_id} if {cond_rb}")
                elif b.branch_kind == "default":
                    default_target = b.target_id
                else:
                    lines.append(f"      active_branches << :{b.target_id}")
            if default_target:
                lines.append(f"      active_branches << :{default_target} if active_branches.empty?")
            lines.append("      active_branches")
            return lines

        when_branches = [b for b in gw.branches if b.branch_kind == "when" and b.condition is not None]
        default_branches = [b for b in gw.branches if b.branch_kind != "when"]
        default_target = default_branches[0].target_id if default_branches else None

        if not when_branches:
            if default_target:
                lines.append(f"      [:{default_target}]")
            else:
                lines.append("      []")
            return lines

        for idx, b in enumerate(when_branches):
            cond_rb = self.transpiler.transpile(b.condition, context_var="@context")
            keyword = "if" if idx == 0 else "elsif"
            lines.append(f"      {keyword} {cond_rb}")
            lines.append(f"        [:{b.target_id}]")

        lines.append("      else")
        if default_target:
            lines.append(f"        [:{default_target}]")
        else:
            lines.append("        []")
        lines.append("      end")
        return lines
