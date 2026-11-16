"""HTTP routes for the processes feature (import, compile, simulate, and validate-trace)."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Annotated, Any, Dict, Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile

from ..code_generation.ruby.generator import RubyCodeGenerator, to_snake_case
from ..flowspec.ast.emitter import FlowSpecEmitter
from ..flowspec.lexer.lexer import FlowSpecLexicalError
from ..flowspec.parser.parser import FlowSpecParser, FlowSpecSyntaxError
from ..flowspec.semantic_analysis.analyzer import FlowSpecSemanticAnalyzer
from ..flowspec.semantic_analysis.simulator import FlowSpecSimulator
from ..formal_analysis.services.analysis_service import FormalAnalysisService
from ..formal_analysis.services.trace_validation_service import (
    TraceRequestError,
    TraceValidationService,
    parse_trace_request,
)
from .dependencies import import_analyzable_process, import_bpmn_document
from .import_response import build_import_response
from .samples.repository import (
    FileSystemSampleProcessRepository,
    SampleProcessRepository,
    default_samples_directory,
)
from .services.process_service import ProcessImportService

router = APIRouter(prefix="/api/v1/processes", tags=["processes"])

process_service = ProcessImportService()
formal_service = FormalAnalysisService()
trace_validation_service = TraceValidationService()
flowspec_emitter = FlowSpecEmitter()
flowspec_parser = FlowSpecParser()
semantic_analyzer = FlowSpecSemanticAnalyzer()
ruby_generator = RubyCodeGenerator()
simulator = FlowSpecSimulator()
sample_repository: SampleProcessRepository = FileSystemSampleProcessRepository(default_samples_directory())


@router.get("/samples", summary="List the demo BPMN diagrams")
def list_sample_processes() -> Dict[str, Any]:
    """Catalog of the demo diagrams that can be loaded into the editor."""
    return {
        "samples": [
            {"id": s.id, "filename": s.filename, "name": s.name, "process_id": s.process_id}
            for s in sample_repository.list()
        ]
    }


@router.get(
    "/samples/{sample_id}",
    summary="Download the BPMN XML of a demo diagram",
    response_class=Response,
    responses={
        200: {"content": {"application/xml": {}}, "description": "The raw BPMN 2.0 XML."},
        404: {"description": "Unknown sample id."},
    },
)
def get_sample_process(sample_id: str) -> Response:
    """Returns the raw BPMN XML of one demo diagram, ready for bpmn-js."""
    xml = sample_repository.get_xml(sample_id)
    if xml is None:
        raise HTTPException(status_code=404, detail={"message": f"Sample '{sample_id}' was not found."})
    filename = next((s.filename for s in sample_repository.list() if s.id == sample_id), f"{sample_id}.bpmn")
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/import",
    summary="Import a BPMN file without analyzing it",
    responses={422: {"description": "The document could not be imported (error diagnostics in `detail`)."}},
)
def import_bpmn_process(
    file: UploadFile = File(..., description="Single .bpmn or .xml file to import"),
) -> Dict[str, Any]:
    """Imports a BPMN 2.0 file and returns the neutral process model plus every diagnostic."""
    result = import_bpmn_document(file, process_service)
    return build_import_response(result)


@router.post("/compile")
def compile_bpmn_process(
    file: UploadFile = File(..., description="Single .bpmn or .xml file to compile"),
    format: Annotated[
        Literal["json", "zip"],
        Query(description="Response format: 'json' (default) or 'zip' (downloadable Rails project)"),
    ] = "json",
) -> Any:
    """Accepts a single .bpmn file, validates it, runs formal automata analysis,
    emits and compiles FlowSpec DSL, and returns either the full compilation JSON
    or a downloadable Ruby on Rails + Sidekiq project ZIP."""
    graph, diagnostics, bpmn_node_ids = import_analyzable_process(file, process_service)

    formal_report = formal_service.analyze(graph)

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

    semantic_result = semantic_analyzer.analyze(process_ast)

    ruby_output = ruby_generator.generate(
        ast=process_ast,
        sample_payload=semantic_result.data_contract.get("sample_payload", {}),
        acyclic_paths=formal_report.acyclic_paths,
        variable_symbols=semantic_result.variable_symbols,
    )

    if format == "zip":
        project_slug = f"{to_snake_case(graph.process_id)}_rails"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for rel_path, content in ruby_output.to_dict()["files"].items():
                info = zipfile.ZipInfo(f"{project_slug}/{rel_path}")
                mode = 0o755 if rel_path.startswith("bin/") else 0o644
                info.external_attr = (0o100000 | mode) << 16
                archive.writestr(info, content.encode("utf-8"))
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_slug}.zip"'},
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
        "bpmn_node_ids": bpmn_node_ids,
        "data_contract": semantic_result.data_contract,
        "formal_analysis": formal_report.to_dict(),
        "flowspec": {
            "chomsky_classification": "Type-2",
            "code": flowspec_code,
            "symbol_table": semantic_result.to_dict()["symbol_table"],
        },
        "generated_ruby": ruby_output.to_dict(),
    }


@router.post("/simulate")
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
    bpmn_node_ids: Optional[Dict[str, str]] = None
    if file is not None:
        graph, _, bpmn_node_ids = import_analyzable_process(file, process_service)
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
        "bpmn_node_ids": bpmn_node_ids,
        "simulation": sim_result.to_dict(),
    }


@router.post(
    "/validate-trace",
    summary="Check whether a trace is a possible execution of the BPMN model",
    responses={422: {"description": "Invalid trace fields, unreadable document or diagram that cannot be analyzed."}},
)
def validate_trace(
    file: UploadFile = File(..., description="Single .bpmn or .xml file whose DFA defines the valid traces"),
    trace: Optional[str] = Form(None, description="JSON array of DFA symbols, e.g. [\"start_1\", \"task_1\"]"),
    bpmn_trace: Optional[str] = Form(None, description="JSON array of original BPMN node ids (alternative to 'trace')"),
) -> Dict[str, Any]:
    """Stateless membership check: is the trace accepted by the DFA inferred from the uploaded model?

    Send exactly one of ``trace`` (symbols) or ``bpmn_trace`` (BPMN ids). A rejected trace is still HTTP 200.
    """
    try:
        parsed_trace, uses_bpmn_ids = parse_trace_request(trace, bpmn_trace)
    except TraceRequestError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc

    graph, _, bpmn_node_ids = import_analyzable_process(file, process_service)
    dfa = formal_service.analyze(graph).dfa

    if uses_bpmn_ids:
        validation = trace_validation_service.validate_bpmn_trace(graph, dfa, bpmn_node_ids, parsed_trace)
    else:
        validation = trace_validation_service.validate(graph, dfa, parsed_trace)
    return {"process_id": graph.process_id, "bpmn_node_ids": bpmn_node_ids, "validation": validation}
