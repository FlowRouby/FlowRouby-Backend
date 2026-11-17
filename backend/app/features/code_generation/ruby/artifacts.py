"""Target-code templates for the supporting Ruby files.

Fills the fixed Ruby templates with data taken from the AST: form objects, Sidekiq HTTP jobs,
delegate service stubs, decision stubs and the RSpec file.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...flowspec.ast.nodes import TaskNodeAST
from .expression_transpiler import RubyExpressionTranspiler
from .naming import to_snake_case
from .templates.rails_templates import (
    DECISION_RULE_STUB_TEMPLATE,
    DELEGATE_SERVICE_TEMPLATE,
    FORM_OBJECT_TEMPLATE,
    RSPEC_WORKFLOW_TEMPLATE,
    SIDEKIQ_HTTP_JOB_TEMPLATE,
)

_RUBY_TYPES = {
    "boolean": ":boolean",
    "bool": ":boolean",
    "long": ":integer",
    "integer": ":integer",
    "int": ":integer",
    "string": ":string",
}


def build_form_object(node: TaskNodeAST, form_cls: str) -> str:
    attr_lines: List[str] = []
    val_lines: List[str] = []
    for ff in node.form_fields:
        rb_type = _RUBY_TYPES.get(ff.field_type.lower(), ":string")
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


def build_http_job(node: TaskNodeAST, job_cls: str, transpiler: RubyExpressionTranspiler) -> str:
    hc = node.http_connector
    assert hc is not None
    headers_pairs = ", ".join(f'"{k}" => "{v}"' for k, v in hc.headers.items())
    headers_ruby = f"{{ {headers_pairs} }}" if headers_pairs else "{}"

    if hc.payload_fields:
        payload_pairs = ",\n          ".join(
            f'"{k}" => {transpiler.transpile(v, context_var="ctx")}' for k, v in hc.payload_fields.items()
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
        env_prefix=to_snake_case(job_cls).upper(),
        url=hc.url,
        method=hc.method,
        headers_ruby=headers_ruby,
        payload_block=payload_block,
        output_assignment=output_assignment,
    )


def build_service_stub(node: TaskNodeAST, service_cls: str) -> str:
    return DELEGATE_SERVICE_TEMPLATE.format(
        node_id=node.id,
        node_name=node.name,
        delegate_class=node.delegate_class,
        service_class_name=service_cls,
    )


def build_decision_stub(node: TaskNodeAST, decision_cls: str, result_variable: str) -> str:
    return DECISION_RULE_STUB_TEMPLATE.format(
        node_id=node.id,
        node_name=node.name,
        decision_ref=node.decision_ref,
        result_variable=result_variable,
        decision_class_name=decision_cls,
    )


def build_rspec(
    workflow_class_name: str,
    start_node_id: str,
    sample_payload: Dict[str, Any],
    acyclic_paths: List[List[str]],
    async_http_jobs: List[str],
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
    if async_http_jobs:
        path_specs.append(
            '    it "reports Sidekiq enqueue status consistently when HTTP jobs run asynchronously" do\n'
            '      result = described_class.call(sample_payload)\n'
            '      expected_status = result[:enqueued_jobs].empty? ? "completed" : "enqueued"\n'
            '      expect(result[:status]).to eq(expected_status)\n'
            "    end"
        )
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
