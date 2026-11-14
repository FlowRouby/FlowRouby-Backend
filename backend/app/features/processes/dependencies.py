"""HTTP import helpers for the processes feature."""

from __future__ import annotations

from typing import List, Tuple

from fastapi import HTTPException, UploadFile

from .intermediate_model.diagnostics import Diagnostic, ImportResult
from .intermediate_model.models import ProcessGraph
from .services.process_service import ProcessImportService


def import_bpmn_document(file: UploadFile, service: ProcessImportService) -> ImportResult:
    """Imports an uploaded BPMN file or raises HTTP 422 with error diagnostics."""
    result = service.import_single_bpmn(file.file.read(), filename=file.filename, file_count=1)
    if result.has_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The BPMN document could not be imported.",
                "diagnostics": [d.to_dict() for d in result.errors],
            },
        )
    return result


def import_analyzable_process(
    file: UploadFile, service: ProcessImportService
) -> Tuple[ProcessGraph, List[Diagnostic]]:
    """Imports an uploaded BPMN file and requires it to be supported for formal analysis."""
    result = import_bpmn_document(file, service)
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

