"""Safe XML loading for user-supplied BPMN documents.

``defusedxml`` rejects DTDs and entity declarations outright (XXE, entity expansion, external
resources). BPMN documents never need them, so no feature is lost.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException


class XmlLoadError(Exception):
    """The document cannot be read as safe, well-formed XML."""


def load_xml(content: str | bytes) -> Element:
    """Parses XML text or bytes into an element tree root, rejecting unsafe constructs."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    try:
        return SafeElementTree.fromstring(data, forbid_dtd=True)
    except ParseError as exc:
        raise XmlLoadError(f"Malformed XML document: {exc}") from exc
    except DefusedXmlException as exc:
        raise XmlLoadError(
            "DTDs and entity declarations are not allowed in BPMN documents."
        ) from exc
