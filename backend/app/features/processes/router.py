"""HTTP routes of the processes feature that only import BPMN (no analysis, no code generation)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile

from .import_response import build_import_response
from .services.process_service import ProcessImportService

router = APIRouter(prefix="/api/v1/processes", tags=["processes"])
process_service = ProcessImportService()


@router.post(
    "/import",
    summary="Import a BPMN file without analyzing it",
    responses={422: {"description": "The document could not be imported (error diagnostics in `detail`)."}},
)
def import_bpmn_process(
    file: UploadFile = File(..., description="Single .bpmn or .xml file to import"),
) -> Dict[str, Any]:
    """Imports a BPMN 2.0 file and returns the neutral process model plus every diagnostic.

    Nothing is analyzed, emitted or stored. The response is `200` even when warnings exist or
    analysis is blocked, so the diagram can still be displayed. `supported` tells whether formal
    analysis can run on this import (`false` when any diagnostic has `blocksAnalysis: true`).
    A document that cannot be imported at all answers `422` with the error diagnostics.
    """
    result = process_service.import_single_bpmn(file.file.read(), filename=file.filename, file_count=1)
    if result.has_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The BPMN document could not be imported.",
                "diagnostics": [d.to_dict() for d in result.errors],
            },
        )
    return build_import_response(result)
