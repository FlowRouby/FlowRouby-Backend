"""Safe XML loading for user-supplied BPMN documents.

``defusedxml`` rejects DTDs and entity declarations outright (XXE, entity expansion, external
resources). BPMN documents never need them, so no feature is lost.

Every element is also stamped with the line where its start tag begins (``source_line``) so
diagnostics can point at the source. The line is read from the underlying expat parser while the
tree is built, which keeps defusedxml's protections intact.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from xml.etree.ElementTree import Element, ParseError, TreeBuilder

from defusedxml.ElementTree import DefusedXMLParser
from defusedxml.common import DefusedXmlException


class SourceElement(Element):
    """An XML element that remembers the line of its start tag."""

    source_line: Optional[int] = None


class XmlLoadError(Exception):
    """The document cannot be read as safe, well-formed XML."""

    def __init__(self, message: str, line: Optional[int] = None):
        super().__init__(message)
        self.line = line


def line_of(element: Element) -> Optional[int]:
    """Line of the element's start tag, or None when it was not built by ``load_xml``."""
    return getattr(element, "source_line", None)


def _current_line(parser: DefusedXMLParser) -> Optional[int]:
    try:
        return parser.parser.CurrentLineNumber
    except Exception:
        return None


def load_xml(content: str | bytes) -> SourceElement:
    """Parses XML text or bytes into an element tree root, rejecting unsafe constructs."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    holder: Dict[str, Any] = {}

    def element_factory(tag: str, attrib: Dict[str, str]) -> SourceElement:
        element = SourceElement(tag, attrib)
        element.source_line = _current_line(holder["parser"])
        return element

    parser = DefusedXMLParser(target=TreeBuilder(element_factory=element_factory), forbid_dtd=True)
    holder["parser"] = parser
    try:
        parser.feed(data)
        return parser.close()
    except ParseError as exc:
        position = getattr(exc, "position", None)
        raise XmlLoadError(f"Malformed XML document: {exc}", line=position[0] if position else None) from exc
    except DefusedXmlException as exc:
        raise XmlLoadError(
            "DTDs and entity declarations are not allowed in BPMN documents.", line=_current_line(parser)
        ) from exc
