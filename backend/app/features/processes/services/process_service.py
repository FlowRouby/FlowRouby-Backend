"""Service layer for validating and importing single BPMN 2.0 files into Intermediate Models."""

from __future__ import annotations

from typing import List, Optional
from ..bpmn_importer.importer import BpmnImporter, BpmnImportValidationError
from ..intermediate_model.models import ProcessGraph


class ProcessImportService:
    """Coordinates single-file BPMN validation and conversion to ProcessGraph."""

    def __init__(self, validate_xsd: bool = True):
        self.importer = BpmnImporter(validate_xsd=validate_xsd)

    def import_single_bpmn(
        self,
        xml_content: str | bytes,
        filename: Optional[str] = None,
        file_count: int = 1,
    ) -> ProcessGraph:
        """Validates the single-BPMN-per-request rule and parses the document."""
        if file_count != 1:
            raise BpmnImportValidationError(
                f"Only a single BPMN file is allowed per request (received {file_count})."
            )
        if filename and not filename.lower().endswith((".bpmn", ".xml")):
            raise BpmnImportValidationError(
                f"Invalid file extension for '{filename}'. Expected a .bpmn or .xml file."
            )

        graph = self.importer.parse_string(xml_content, filename=filename)
        if not graph.start_nodes:
            raise BpmnImportValidationError(
                f"Process '{graph.process_id}' must contain at least one <bpmn:startEvent>."
            )
        if not graph.end_nodes:
            raise BpmnImportValidationError(
                f"Process '{graph.process_id}' must contain at least one <bpmn:endEvent>."
            )
        return graph

