"""Service layer for importing BPMN uploads into the Intermediate Model."""

from __future__ import annotations

from typing import Optional

from ..bpmn_importer.importer import BpmnImporter
from ..intermediate_model.diagnostics import Diagnostic, DiagnosticCode, ImportResult, Severity

ALLOWED_EXTENSIONS = (".bpmn", ".xml")


class ProcessImportService:
    """Applies the upload rules of a request, then delegates parsing to the importer."""

    def __init__(self, importer: Optional[BpmnImporter] = None):
        self.importer = importer or BpmnImporter()

    def import_single_bpmn(
        self,
        xml_content: str | bytes,
        filename: Optional[str] = None,
        file_count: int = 1,
    ) -> ImportResult:
        """Validates the one-file-per-request and extension rules, then imports the document."""
        if file_count != 1:
            return self._rejected(f"Only a single BPMN file is allowed per request (received {file_count}).")
        if filename and not filename.lower().endswith(ALLOWED_EXTENSIONS):
            return self._rejected(f"Invalid file extension for '{filename}'. Expected a .bpmn or .xml file.")
        return self.importer.import_xml(xml_content)

    @staticmethod
    def _rejected(message: str) -> ImportResult:
        return ImportResult(
            document=None,
            diagnostics=[Diagnostic(Severity.ERROR, DiagnosticCode.INVALID_UPLOAD, message)],
        )
