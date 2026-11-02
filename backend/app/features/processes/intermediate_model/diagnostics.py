"""Structured import diagnostics.

Three situations are kept apart:

* ``error`` - an XML/BPMN problem that prevents building a consistent IR (``document`` is ``None``).
* ``warning`` / ``info`` - something was imported and preserved, but FlowRouby does not (fully)
  interpret it. When ``blocks_analysis`` is true, formal analysis must not run on the result.
* Restrictions of the FlowRouby import/analysis profile (for example "a process needs a start
  event") are reported with their own codes; they are profile rules, not universal BPMN rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .models import BpmnDocument, ProcessGraph


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosticCode(str, Enum):
    # Errors: no consistent IR can be built
    XML_MALFORMED = "XML_MALFORMED"
    NOT_BPMN = "NOT_BPMN"
    NO_PROCESS = "NO_PROCESS"
    MISSING_ID = "MISSING_ID"
    DUPLICATE_ID = "DUPLICATE_ID"
    MISSING_REF_ATTRIBUTE = "MISSING_REF_ATTRIBUTE"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    NO_START_EVENT = "NO_START_EVENT"  # FlowRouby profile rule
    NO_END_EVENT = "NO_END_EVENT"  # FlowRouby profile rule
    # Warnings and info: imported, with limits
    UNSUPPORTED_ELEMENT = "UNSUPPORTED_ELEMENT"
    PRESERVED_NOT_ANALYZABLE = "PRESERVED_NOT_ANALYZABLE"
    MULTIPLE_START_EVENTS = "MULTIPLE_START_EVENTS"  # FlowRouby profile rule
    MULTIPLE_PROCESSES = "MULTIPLE_PROCESSES"  # FlowRouby profile rule
    DISCONNECTED_NODE = "DISCONNECTED_NODE"
    GATEWAY_WITHOUT_OUTGOING = "GATEWAY_WITHOUT_OUTGOING"
    XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT = "XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT"
    IGNORED_ELEMENT = "IGNORED_ELEMENT"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: DiagnosticCode
    message: str
    element_id: Optional[str] = None
    element_type: Optional[str] = None  # original BPMN local tag name
    process_id: Optional[str] = None
    blocks_analysis: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code.value,
            "message": self.message,
            "elementId": self.element_id,
            "elementType": self.element_type,
            "processId": self.process_id,
            "blocksAnalysis": self.blocks_analysis,
        }


@dataclass
class ImportResult:
    """Outcome of an import: the document (``None`` on error) plus every diagnostic found."""

    document: Optional[BpmnDocument] = None
    diagnostics: List[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def analysis_blockers(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.blocks_analysis]

    @property
    def analysis_supported(self) -> bool:
        return self.document is not None and not self.analysis_blockers

    @property
    def process(self) -> Optional[ProcessGraph]:
        """The only process of the document, or ``None`` when there is not exactly one."""
        if self.document is not None and len(self.document.processes) == 1:
            return self.document.processes[0]
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supported": self.analysis_supported,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }
