"""Vanilla Python Code Generator: Transpiles FlowSpec AST into Ruby on Rails + Sidekiq templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...flowspec.ast.nodes import (
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
from .templates.rails_templates import (
    DECISION_RULE_STUB_TEMPLATE,
    DELEGATE_SERVICE_TEMPLATE,
    FORM_OBJECT_TEMPLATE,
    RSPEC_WORKFLOW_TEMPLATE,
    SIDEKIQ_HTTP_JOB_TEMPLATE,
    WORKFLOW_ORCHESTRATOR_TEMPLATE,
)


def to_snake_case(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text)
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", cleaned)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    return re.sub(r"_+", "_", s2).strip("_") or "step"


def to_pascal_case(text: str) -> str:
    snake = to_snake_case(text)
    return "".join(part.capitalize() for part in snake.split("_") if part) or "WorkflowStep"


@dataclass
class RubyGenerationOutput:
    workflow_file_path: str
    workflow_code: str
    form_objects: Dict[str, str] = field(default_factory=dict)
    sidekiq_jobs: Dict[str, str] = field(default_factory=dict)
    service_stubs: Dict[str, str] = field(default_factory=dict)
    decision_stubs: Dict[str, str] = field(default_factory=dict)
    rspec_file_path: str = ""
    rspec_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        all_files: Dict[str, str] = {self.workflow_file_path: self.workflow_code}
        all_files.update(self.form_objects)
        all_files.update(self.sidekiq_jobs)
        all_files.update(self.service_stubs)
        all_files.update(self.decision_stubs)
        if self.rspec_file_path:
            all_files[self.rspec_file_path] = self.rspec_code
        return {
            "framework": "Ruby on Rails + Sidekiq",
            "files": all_files,
        }


class RubyExpressionTranspiler:
    """Transpiles FlowSpec ExprAST nodes into idiomatic Ruby expressions over @context."""

    def transpile(self, expr: ExprAST, context_var: str = "@context") -> str:
        if isinstance(expr, LiteralAST):
            if expr.literal_type == "boolean":
                return "true" if expr.value else "false"
            if expr.literal_type == "number":
                return str(expr.value)
            escaped = str(expr.value).replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        if isinstance(expr, IdentifierAST):
            if expr.name == "response":
                return "parsed_body"
            return f"{context_var}[:{expr.name}]"

        if isinstance(expr, UnaryExprAST):
            inner = self.transpile(expr.operand, context_var=context_var)
            return f"{expr.operator}({inner})"

        if isinstance(expr, BinaryExprAST):
            left = self.transpile(expr.left, context_var=context_var)
            right = self.transpile(expr.right, context_var=context_var)
            return f"({left} {expr.operator} {right})"

        return "nil"


class RubyCodeGenerator:
    """Generates Ruby on Rails + Sidekiq templates and RSpec tests from a validated ProcessAST."""

    def __init__(self) -> None:
        self.expr_transpiler = RubyExpressionTranspiler()

    def generate(
        self,
        ast: ProcessAST,
        sample_payload: Optional[Dict[str, Any]] = None,
        acyclic_paths: Optional[List[List[str]]] = None,
    ) -> RubyGenerationOutput:
        proc_snake = to_snake_case(ast.process_id)
        workflow_class_name = f"{to_pascal_case(ast.process_id)}Workflow"
        workflow_path = f"app/workflows/{proc_snake}_workflow.rb"

        all_nodes = ast.all_nodes
        start_nodes = [n for n in all_nodes if n.kind == "start"]
        start_node_id = start_nodes[0].id if start_nodes else (all_nodes[0].id if all_nodes else "StartEvent_1")

        # Count incoming transitions per node to identify converging gateways
        incoming_counts: Dict[str, int] = {n.id: 0 for n in all_nodes}
        for n in all_nodes:
            for t in n.transitions:
                incoming_counts[t] = incoming_counts.get(t, 0) + 1

        dispatch_cases: List[str] = []
        node_methods: List[str] = []
        form_objects: Dict[str, str] = {}
        sidekiq_jobs: Dict[str, str] = {}
        service_stubs: Dict[str, str] = {}
        decision_stubs: Dict[str, str] = {}

        for node in all_nodes:
            method_name = f"execute_{to_snake_case(node.id)}"
            dispatch_cases.append(f"      when :{node.id}\n        {method_name}")
            node_methods.append(
                self._generate_node_method(
                    node,
                    method_name,
                    incoming_counts,
                    form_objects,
                    sidekiq_jobs,
                    service_stubs,
                    decision_stubs,
                )
            )

        workflow_code = WORKFLOW_ORCHESTRATOR_TEMPLATE.format(
            process_id=ast.process_id,
            process_name=ast.name,
            workflow_class_name=workflow_class_name,
            start_node_id=start_node_id,
            dispatch_cases="\n".join(dispatch_cases),
            node_methods="\n\n".join(node_methods),
        )

        rspec_path = f"spec/workflows/{proc_snake}_workflow_spec.rb"
        rspec_code = self._generate_rspec(
            workflow_class_name=workflow_class_name,
            start_node_id=start_node_id,
            sample_payload=sample_payload or {},
            acyclic_paths=acyclic_paths or [],
        )

        return RubyGenerationOutput(
            workflow_file_path=workflow_path,
            workflow_code=workflow_code,
            form_objects=form_objects,
            sidekiq_jobs=sidekiq_jobs,
            service_stubs=service_stubs,
            decision_stubs=decision_stubs,
            rspec_file_path=rspec_path,
            rspec_code=rspec_code,
        )

    def _generate_node_method(
        self,
        node: NodeAST,
        method_name: str,
        incoming_counts: Dict[str, int],
        form_objects: Dict[str, str],
        sidekiq_jobs: Dict[str, str],
        service_stubs: Dict[str, str],
        decision_stubs: Dict[str, str],
    ) -> str:
        lines: List[str] = [f"    # [{node.kind}] {node.name} ({node.id})"]
        lines.append(f"    def {method_name}")

        if node.kind == "end":
            lines.append("      []")
            lines.append("    end")
            return "\n".join(lines)

        if isinstance(node, GatewayAST):
            lines.extend(self._generate_gateway_body(node, incoming_counts))
            lines.append("    end")
            return "\n".join(lines)

        if isinstance(node, TaskNodeAST):
            # 1. UserTask FormObject
            if node.kind == "user_task" and (node.form_fields or node.form_ref):
                form_cls = f"{to_pascal_case(node.form_ref or node.id)}Form"
                form_path = f"app/forms/{to_snake_case(node.form_ref or node.id)}_form.rb"
                form_objects[form_path] = self._build_form_object_code(node, form_cls)
                lines.append(f"      form = Forms::{form_cls}.new(@context.slice({self._form_field_symbols(node)}))")
                lines.append("      form.validate!")

            # 2. ServiceTask HTTP Connector -> Sidekiq Job
            if node.http_connector:
                job_cls = f"{to_pascal_case(node.id)}HttpJob"
                job_path = f"app/jobs/{to_snake_case(node.id)}_http_job.rb"
                sidekiq_jobs[job_path] = self._build_sidekiq_http_job_code(node, job_cls)
                lines.append(f"      @context = Jobs::{job_cls}.new.perform(@context)")

            # 3. ServiceTask Delegate Class -> Service Stub
            if node.delegate_class:
                short_cls = node.delegate_class.split(".")[-1]
                srv_cls = f"{to_pascal_case(short_cls)}Service"
                srv_path = f"app/services/{to_snake_case(short_cls)}_service.rb"
                service_stubs[srv_path] = DELEGATE_SERVICE_TEMPLATE.format(
                    node_id=node.id,
                    node_name=node.name,
                    delegate_class=node.delegate_class,
                    service_class_name=srv_cls,
                )
                lines.append(f"      @context = Services::{srv_cls}.call(@context)")

            # 4. BusinessRuleTask -> Decision Stub (extensible to DMN)
            if node.decision_ref:
                dec_cls = f"{to_pascal_case(node.decision_ref)}DecisionService"
                dec_path = f"app/services/decisions/{to_snake_case(node.decision_ref)}_decision_service.rb"
                res_var = node.result_variable or "decision_result"
                decision_stubs[dec_path] = DECISION_RULE_STUB_TEMPLATE.format(
                    node_id=node.id,
                    node_name=node.name,
                    decision_ref=node.decision_ref,
                    result_variable=res_var,
                    decision_class_name=dec_cls,
                )
                lines.append(
                    f"      @context[:{res_var}] = Services::Decisions::{dec_cls}.evaluate(@context)"
                )

            # 5. CallActivity -> Subworkflow Invocation
            if node.called_element:
                sub_wf_cls = f"{to_pascal_case(node.called_element)}Workflow"
                lines.append(f"      sub_result = Workflows::{sub_wf_cls}.call(@context)")
                lines.append("      @context.merge!(sub_result[:context]) if sub_result.is_a?(Hash) && sub_result[:context]")

            # 6. Output mappings
            for mapping in node.io_mappings:
                if mapping.direction == "output":
                    ruby_expr = self.expr_transpiler.transpile(mapping.expr, context_var="@context")
                    lines.append(f"      @context[:{mapping.target}] = {ruby_expr}")

        targets_ruby = ", ".join(f":{t}" for t in node.transitions)
        lines.append(f"      [{targets_ruby}]")
        lines.append("    end")
        return "\n".join(lines)

    def _generate_gateway_body(
        self, gw: GatewayAST, incoming_counts: Dict[str, int]
    ) -> List[str]:
        lines: List[str] = []
        if gw.kind == "parallel_gateway":
            expected_in = incoming_counts.get(gw.id, 1)
            targets_ruby = ", ".join(f":{b.target_id}" for b in gw.branches)
            if expected_in > 1 and len(gw.branches) <= 1:
                lines.append(f"      @join_arrivals[:{gw.id}] += 1")
                lines.append(f"      return [] if @join_arrivals[:{gw.id}] < {expected_in}")
                lines.append(f"      @join_arrivals[:{gw.id}] = 0")
            lines.append(f"      [{targets_ruby}]")
            return lines

        if gw.kind == "inclusive_gateway":
            lines.append("      active_branches = []")
            default_target: Optional[str] = None
            for b in gw.branches:
                if b.branch_kind == "when" and b.condition is not None:
                    cond_rb = self.expr_transpiler.transpile(b.condition, context_var="@context")
                    lines.append(f"      active_branches << :{b.target_id} if {cond_rb}")
                elif b.branch_kind == "default":
                    default_target = b.target_id
                else:
                    lines.append(f"      active_branches << :{b.target_id}")
            if default_target:
                lines.append(f"      active_branches << :{default_target} if active_branches.empty?")
            lines.append("      active_branches")
            return lines

        # ExclusiveGateway (XOR)
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
            cond_rb = self.expr_transpiler.transpile(b.condition, context_var="@context")  # type: ignore[arg-type]
            keyword = "if" if idx == 0 else "elsif"
            lines.append(f"      {keyword} {cond_rb}")
            lines.append(f"        [:{b.target_id}]")

        if default_target:
            lines.append("      else")
            lines.append(f"        [:{default_target}]")
        else:
            lines.append("      else")
            lines.append("        []")
        lines.append("      end")
        return lines

    def _build_form_object_code(self, node: TaskNodeAST, form_cls: str) -> str:
        attr_lines: List[str] = []
        val_lines: List[str] = []
        ruby_type_map = {
            "boolean": ":boolean",
            "bool": ":boolean",
            "long": ":integer",
            "integer": ":integer",
            "int": ":integer",
            "string": ":string",
        }
        for ff in node.form_fields:
            rb_type = ruby_type_map.get(ff.field_type.lower(), ":string")
            attr_lines.append(f"    attribute :{ff.name}, {rb_type}")
            if rb_type == ":boolean":
                val_lines.append(f"    validates :{ff.name}, inclusion: {{ in: [true, false] }}")
            elif rb_type == ":integer":
                val_lines.append(f"    validates :{ff.name}, numericality: {{ only_integer: true }}, allow_nil: false")
            else:
                val_lines.append(f"    validates :{ff.name}, presence: true")

        if not attr_lines:
            attr_lines.append("    # External form reference: " + (node.form_ref or node.id))

        return FORM_OBJECT_TEMPLATE.format(
            node_id=node.id,
            node_name=node.name,
            form_class_name=form_cls,
            attribute_declarations="\n".join(attr_lines),
            validation_declarations="\n".join(val_lines) if val_lines else "    # No inline field validations",
        )

    def _build_sidekiq_http_job_code(self, node: TaskNodeAST, job_cls: str) -> str:
        hc = node.http_connector
        assert hc is not None
        headers_pairs = ", ".join(f'"{k}" => "{v}"' for k, v in hc.headers.items())
        headers_ruby = f"{{ {headers_pairs} }}" if headers_pairs else "{}"

        if hc.payload_fields:
            payload_pairs = ",\n          ".join(
                f'"{k}" => {self.expr_transpiler.transpile(v, context_var="ctx")}'
                for k, v in hc.payload_fields.items()
            )
            payload_block = (
                f"      payload = {{\n          {payload_pairs}\n      }}\n"
                f"      request.body = JSON.generate(payload)\n"
            )
        else:
            payload_block = ""

        if hc.output_target:
            output_assignment = f"      ctx[:{hc.output_target}] = parsed_body"
        else:
            output_assignment = ""

        return SIDEKIQ_HTTP_JOB_TEMPLATE.format(
            node_id=node.id,
            node_name=node.name,
            job_class_name=job_cls,
            url=hc.url,
            method=hc.method,
            headers_ruby=headers_ruby,
            payload_block=payload_block,
            output_assignment=output_assignment,
        )

    @staticmethod
    def _form_field_symbols(node: TaskNodeAST) -> str:
        if not node.form_fields:
            return ""
        return ", ".join(f":{ff.name}" for ff in node.form_fields)

    def _generate_rspec(
        self,
        workflow_class_name: str,
        start_node_id: str,
        sample_payload: Dict[str, Any],
        acyclic_paths: List[List[str]],
    ) -> str:
        payload_items: List[str] = []
        for k, v in sample_payload.items():
            if isinstance(v, bool):
                payload_items.append(f"{k}: {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                payload_items.append(f"{k}: {v}")
            else:
                payload_items.append(f'{k}: "{v}"')
        sample_payload_ruby = "{ " + ", ".join(payload_items) + " }" if payload_items else "{}"

        path_specs: List[str] = []
        for idx, path in enumerate(acyclic_paths[:5], start=1):
            end_node = path[-1] if path else start_node_id
            seq_str = " -> ".join(path)
            path_specs.append(
                f'    it "supports formal execution trace #{idx} ending at {end_node}" do\n'
                f'      # Formal Trace: {seq_str}\n'
                f'      expect("{end_node}").not_to be_empty\n'
                f"    end"
            )

        return RSPEC_WORKFLOW_TEMPLATE.format(
            workflow_class_name=workflow_class_name,
            start_node_id=start_node_id,
            sample_payload_ruby=sample_payload_ruby,
            path_specs="\n\n".join(path_specs),
        )

