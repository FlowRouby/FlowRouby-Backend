"""FastAPI Entrypoint for the BPMN -> FlowSpec -> Formal Automata -> Ruby on Rails Compiler."""

from __future__ import annotations

import inspect
import json
from typing import Any, Dict, List, Optional, Tuple

import starlette.routing
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

# Compatibility shim for environments with Starlette >= 1.0 and FastAPI 0.115.x
if not hasattr(FastAPI, "max_body_size"):
    FastAPI.max_body_size = None  # type: ignore[attr-defined]

if "on_startup" not in inspect.signature(starlette.routing.Router.__init__).parameters:
    _orig_router_init = starlette.routing.Router.__init__

    def _compat_router_init(self: Any, *args: Any, on_startup: Any = None, on_shutdown: Any = None, **kwargs: Any) -> None:
        _orig_router_init(self, *args, **kwargs)

    starlette.routing.Router.__init__ = _compat_router_init  # type: ignore[method-assign]

from .features.code_generation.ruby.generator import RubyCodeGenerator
from .features.flowspec.ast.emitter import FlowSpecEmitter
from .features.flowspec.lexer.lexer import FlowSpecLexicalError
from .features.flowspec.parser.parser import FlowSpecParser, FlowSpecSyntaxError
from .features.flowspec.semantic_analysis.analyzer import FlowSpecSemanticAnalyzer
from .features.flowspec.semantic_analysis.simulator import FlowSpecSimulator
from .features.formal_analysis.services.analysis_service import FormalAnalysisService
from .features.processes.intermediate_model.diagnostics import Diagnostic
from .features.processes.intermediate_model.models import ProcessGraph
from .features.processes.services.process_service import ProcessImportService
from .features.processes.router import router as processes_router

app = FastAPI(
    title="SHTLNG BPMN -> FlowSpec -> Ruby Compiler API",
    description=(
        "Compiles BPMN 2.0 / Camunda diagrams into the FlowSpec intermediate DSL, "
        "runs formal verification (ε-NFA, DFA, Regular Expressions), simulates flows statelessly, "
        "and generates Ruby on Rails + Sidekiq templates."
    ),
    version="1.0.0",
)

app.include_router(processes_router)

process_service = ProcessImportService()
formal_service = FormalAnalysisService()
flowspec_emitter = FlowSpecEmitter()
flowspec_parser = FlowSpecParser()
semantic_analyzer = FlowSpecSemanticAnalyzer()
ruby_generator = RubyCodeGenerator()
simulator = FlowSpecSimulator()


class FlowSpecCompileRequest(BaseModel):
    flowspec_code: str = Field(..., description="Source code written in the FlowSpec intermediate DSL.")


class FlowSpecSimulateRequest(BaseModel):
    flowspec_code: str = Field(..., description="Source code written in the FlowSpec intermediate DSL.")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Input payload for stateless simulation.")


def _import_bpmn_or_422(
    xml_bytes: bytes, filename: Optional[str], file_count: int
) -> Tuple[ProcessGraph, List[Diagnostic]]:
    """Imports an uploaded BPMN file, or raises HTTP 422 with the diagnostics that explain why not.

    Import errors and analysis blockers are different situations, but both stop the compile and
    simulate pipelines: running formal analysis on a process that was not fully understood would
    analyze a different process than the one the user imported.
    """
    result = process_service.import_single_bpmn(xml_bytes, filename=filename, file_count=file_count)
    if result.has_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The BPMN document could not be imported.",
                "diagnostics": [d.to_dict() for d in result.errors],
            },
        )
    graph = result.process
    if not result.analysis_supported or graph is None:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The BPMN document was imported but cannot be analyzed yet.",
                "diagnostics": [d.to_dict() for d in result.analysis_blockers],
            },
        )
    return graph, result.diagnostics


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok", "service": "bpmn-to-ruby-compiler"}


@app.post("/api/v1/processes/compile")
def compile_bpmn_process(
    files: List[UploadFile] = File(..., description="Single .bpmn file to compile"),
) -> Dict[str, Any]:
    """Accepts a single .bpmn file, validates it, runs formal automata analysis,
    emits and compiles FlowSpec DSL, and returns the Ruby on Rails + Sidekiq templates."""
    upload = files[0]
    xml_bytes = upload.file.read() if len(files) == 1 else b""
    graph, diagnostics = _import_bpmn_or_422(xml_bytes, upload.filename, len(files))

    # 1. Formal Analysis (Chomsky Type 3: ε-NFA -> DFA -> Regular Expression + Deadlock/Loop Detection)
    formal_report = formal_service.analyze(graph)

    # 2. Emit Intermediate DSL (FlowSpec) & Parse into AST (Chomsky Type 2 CFG)
    flowspec_code = flowspec_emitter.emit(graph)
    try:
        process_ast = flowspec_parser.parse(flowspec_code)
    except (FlowSpecLexicalError, FlowSpecSyntaxError) as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "line": exc.line,
                "column": exc.column,
                "flowspec_code": flowspec_code,
            },
        ) from exc

    # 3. Semantic Analysis (Symbol Table & Type Checking)
    semantic_result = semantic_analyzer.analyze(process_ast)

    # 4. Ruby on Rails + Sidekiq Code Generation
    ruby_output = ruby_generator.generate(
        ast=process_ast,
        sample_payload=semantic_result.data_contract.get("sample_payload", {}),
        acyclic_paths=formal_report.acyclic_paths,
    )

    return {
        "metadata": {
            "process_id": graph.process_id,
            "process_name": graph.name or graph.process_id,
            "participant_name": graph.participant_name,
            "is_executable": graph.is_executable,
            "lanes": [l.name or l.id for l in graph.lanes],
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        },
        "validation": {
            "valid": formal_report.is_valid_workflow and semantic_result.valid,
            "diagnostics": [d.to_dict() for d in diagnostics],
            "semantic_errors": semantic_result.errors,
            "semantic_warnings": semantic_result.warnings,
        },
        "data_contract": semantic_result.data_contract,
        "formal_analysis": formal_report.to_dict(),
        "flowspec": {
            "chomsky_classification": "Type-2 (Context-Free Grammar LL(1))",
            "code": flowspec_code,
            "symbol_table": semantic_result.to_dict()["symbol_table"],
        },
        "generated_ruby": ruby_output.to_dict(),
    }


@app.post("/api/v1/flowspec/compile")
def compile_flowspec_direct(request: FlowSpecCompileRequest) -> Dict[str, Any]:
    """Compiles FlowSpec DSL code directly into an AST, runs semantic validation,
    and generates Ruby on Rails + Sidekiq templates."""
    try:
        process_ast = flowspec_parser.parse(request.flowspec_code)
    except (FlowSpecLexicalError, FlowSpecSyntaxError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "line": exc.line, "column": exc.column},
        ) from exc

    semantic_result = semantic_analyzer.analyze(process_ast)
    if not semantic_result.valid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "FlowSpec semantic validation failed.",
                "errors": semantic_result.errors,
            },
        )

    ruby_output = ruby_generator.generate(
        ast=process_ast,
        sample_payload=semantic_result.data_contract.get("sample_payload", {}),
    )

    return {
        "metadata": {
            "process_id": process_ast.process_id,
            "process_name": process_ast.name,
            "lanes": [l.name for l in process_ast.lanes],
            "node_count": len(process_ast.all_nodes),
        },
        "validation": {
            "valid": semantic_result.valid,
            "semantic_errors": semantic_result.errors,
        },
        "data_contract": semantic_result.data_contract,
        "flowspec": {
            "chomsky_classification": "Type-2 (Context-Free Grammar LL(1))",
            "code": request.flowspec_code,
            "symbol_table": semantic_result.to_dict()["symbol_table"],
        },
        "generated_ruby": ruby_output.to_dict(),
    }


@app.post("/api/v1/processes/simulate")
def simulate_bpmn_process(
    file: Optional[UploadFile] = File(None, description="Optional .bpmn file to simulate"),
    flowspec_code: Optional[str] = Form(None, description="Optional FlowSpec DSL source code"),
    input_data: str = Form("{}", description="JSON object string with initial variables and form data"),
) -> Dict[str, Any]:
    """Runs a stateless Dry-Run simulation over either an uploaded .bpmn file or FlowSpec code."""
    try:
        parsed_input = json.loads(input_data) if input_data else {}
        if not isinstance(parsed_input, dict):
            raise ValueError("input_data must be a JSON object")
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"message": f"Invalid input_data JSON: {exc}"}) from exc

    dfa = None
    if file is not None:
        graph, _ = _import_bpmn_or_422(file.file.read(), file.filename, 1)

        formal_report = formal_service.analyze(graph)
        dfa = formal_report.dfa
        code_to_run = flowspec_emitter.emit(graph)
    elif flowspec_code:
        code_to_run = flowspec_code
    else:
        raise HTTPException(
            status_code=422,
            detail={"message": "Provide either a 'file' (.bpmn) or 'flowspec_code' to simulate."},
        )

    try:
        process_ast = flowspec_parser.parse(code_to_run)
    except (FlowSpecLexicalError, FlowSpecSyntaxError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "line": exc.line, "column": exc.column},
        ) from exc

    sim_result = simulator.simulate(ast=process_ast, input_data=parsed_input, dfa=dfa)
    return {
        "process_id": process_ast.process_id,
        "simulation": sim_result.to_dict(),
    }
