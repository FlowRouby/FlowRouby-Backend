"""Code generation stage: turns a validated FlowSpec AST into a Ruby on Rails + Sidekiq project.

``RubyCodeGenerator.generate`` runs the stages in order: the workflow class (``workflow_builder``),
the RSpec file (``artifacts``) and the fixed project files (``scaffold``). Names come from ``naming``
and expressions are translated by ``expression_transpiler``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...flowspec.ast.nodes import ProcessAST
from .artifacts import build_rspec
from .expression_transpiler import RubyExpressionTranspiler
from .naming import to_pascal_case, to_snake_case
from .scaffold import build_rails_scaffold
from .templates.rails_templates import WORKFLOW_ORCHESTRATOR_TEMPLATE
from .workflow_builder import WorkflowBuilder


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
    scaffold_files: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        all_files: Dict[str, str] = dict(self.scaffold_files)
        all_files[self.workflow_file_path] = self.workflow_code
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


class RubyCodeGenerator:
    """Generates Ruby on Rails + Sidekiq templates and RSpec tests from a validated ProcessAST."""

    def __init__(self) -> None:
        self.expr_transpiler = RubyExpressionTranspiler()

    def generate(
        self,
        ast: ProcessAST,
        sample_payload: Optional[Dict[str, Any]] = None,
        acyclic_paths: Optional[List[List[str]]] = None,
        variable_symbols: Optional[Dict[str, Any]] = None,
    ) -> RubyGenerationOutput:
        proc_snake = to_snake_case(ast.process_id)
        workflow_class_name = f"{to_pascal_case(ast.process_id)}Workflow"

        all_nodes = ast.all_nodes
        start_nodes = [n for n in all_nodes if n.kind == "start"]
        start_node_id = start_nodes[0].id if start_nodes else (all_nodes[0].id if all_nodes else "StartEvent_1")

        incoming_counts: Dict[str, int] = {n.id: 0 for n in all_nodes}
        for n in all_nodes:
            for t in n.transitions:
                incoming_counts[t] = incoming_counts.get(t, 0) + 1

        builder = WorkflowBuilder(self.expr_transpiler, incoming_counts, variable_symbols or {})
        dispatch_cases: List[str] = []
        node_methods: List[str] = []
        for node in all_nodes:
            method_name = f"execute_{to_snake_case(node.id)}"
            dispatch_cases.append(f"      when :{node.id}\n        {method_name}")
            node_methods.append(builder.build_node_method(node, method_name))

        workflow_code = WORKFLOW_ORCHESTRATOR_TEMPLATE.format(
            process_id=ast.process_id,
            process_name=ast.name,
            workflow_class_name=workflow_class_name,
            start_node_id=start_node_id,
            dispatch_cases="\n".join(dispatch_cases),
            node_methods="\n\n".join(node_methods),
        )

        rspec_code = build_rspec(
            workflow_class_name=workflow_class_name,
            start_node_id=start_node_id,
            sample_payload=sample_payload or {},
            acyclic_paths=acyclic_paths or [],
            async_http_jobs=builder.async_http_jobs,
        )

        return RubyGenerationOutput(
            workflow_file_path=f"app/workflows/{proc_snake}_workflow.rb",
            workflow_code=workflow_code,
            form_objects=builder.form_objects,
            sidekiq_jobs=builder.sidekiq_jobs,
            service_stubs=builder.service_stubs,
            decision_stubs=builder.decision_stubs,
            rspec_file_path=f"spec/workflows/{proc_snake}_workflow_spec.rb",
            rspec_code=rspec_code,
            scaffold_files=build_rails_scaffold(ast, proc_snake, workflow_class_name),
        )
