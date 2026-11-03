"""BPMN 2.0 importer facade: XML text -> ``ImportResult`` (IR plus diagnostics).

The importer is pure: it reads XML and builds the IR. It knows nothing about HTTP, files
uploaded by users, FlowSpec, Ruby, automata or persistence.
"""

from __future__ import annotations

from ..intermediate_model.diagnostics import Diagnostic, DiagnosticCode, ImportResult, Severity
from .parser import parse_document
from .validator import validate_document
from .xml_loader import XmlLoadError, load_xml


class BpmnImporter:
    def import_xml(self, xml_content: str | bytes) -> ImportResult:
        """Parses BPMN XML. ``document`` is ``None`` when any error diagnostic was produced."""
        try:
            root = load_xml(xml_content)
        except XmlLoadError as exc:
            return ImportResult(
                document=None,
                diagnostics=[Diagnostic(Severity.ERROR, DiagnosticCode.XML_MALFORMED, str(exc), line=exc.line)],
            )

        document, diagnostics = parse_document(root)
        if document is not None:
            diagnostics = diagnostics + validate_document(document)
        result = ImportResult(document=document, diagnostics=diagnostics)
        if result.has_errors:
            result.document = None
        return result

    def import_file(self, file_path: str) -> ImportResult:
        with open(file_path, "rb") as handle:
            return self.import_xml(handle.read())
