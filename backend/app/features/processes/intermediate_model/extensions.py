"""Vendor-neutral container for XML content that is not part of the BPMN 2.0 model.

BPMN allows vendors to attach data in two places:

* attributes in a foreign namespace (for example ``camunda:class``), and
* child elements of ``<bpmn:extensionElements>`` (for example ``camunda:formData``).

Both are kept as a generic tree identified by namespace URI, never by XML prefix, so no
information is lost even for extensions FlowRouby does not understand yet. Interpreting
them is the job of the consumer (see ``flowspec/ast/camunda_extensions.py``), not the IR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


def qualified_name(namespace_uri: Optional[str], local_name: str) -> str:
    """Returns ``{uri}local`` for namespaced names and the bare ``local`` otherwise."""
    return f"{{{namespace_uri}}}{local_name}" if namespace_uri else local_name


@dataclass
class ExtensionElement:
    """One XML element inside ``<bpmn:extensionElements>``.

    ``attributes`` keys use the ``{uri}local`` form for namespaced attributes and the plain
    local name for unqualified ones.
    """

    local_name: str
    namespace_uri: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)
    text: Optional[str] = None
    children: List["ExtensionElement"] = field(default_factory=list)

    def is_a(self, namespace_uri: str, local_name: str) -> bool:
        return self.namespace_uri == namespace_uri and self.local_name == local_name

    def find_children(self, namespace_uri: str, local_name: str) -> List["ExtensionElement"]:
        return [c for c in self.children if c.is_a(namespace_uri, local_name)]

    def find_child(self, namespace_uri: str, local_name: str) -> Optional["ExtensionElement"]:
        matches = self.find_children(namespace_uri, local_name)
        return matches[0] if matches else None

    def attribute(self, namespace_uri: Optional[str], local_name: str) -> Optional[str]:
        return self.attributes.get(qualified_name(namespace_uri, local_name))

    def iter_tree(self) -> Iterator["ExtensionElement"]:
        yield self
        for child in self.children:
            yield from child.iter_tree()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "namespace_uri": self.namespace_uri,
            "local_name": self.local_name,
            "attributes": dict(self.attributes),
            "text": self.text,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class Extensions:
    """Foreign-namespace attributes and ``extensionElements`` children of one BPMN element."""

    attributes: Dict[str, str] = field(default_factory=dict)
    elements: List[ExtensionElement] = field(default_factory=list)

    def attribute(self, namespace_uri: str, local_name: str) -> Optional[str]:
        return self.attributes.get(qualified_name(namespace_uri, local_name))

    def find_all(self, namespace_uri: str, local_name: str) -> List[ExtensionElement]:
        return [e for e in self.elements if e.is_a(namespace_uri, local_name)]

    def find(self, namespace_uri: str, local_name: str) -> Optional[ExtensionElement]:
        matches = self.find_all(namespace_uri, local_name)
        return matches[0] if matches else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "elements": [e.to_dict() for e in self.elements],
        }
