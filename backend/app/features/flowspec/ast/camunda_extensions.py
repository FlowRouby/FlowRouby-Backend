"""Temporary compatibility adapter: reads Camunda data out of the IR's generic extensions.

The IR is vendor neutral; it keeps Camunda attributes and ``extensionElements`` as a generic
tree identified by namespace URI. The FlowSpec emitter still needs a few Camunda concepts to
keep generation working, so this module interprets them on demand. Nothing here is stored
back into the IR.

Camunda extensions consumed today (namespace ``http://camunda.org/schema/1.0/bpmn``):

* attributes: ``formRef`` / ``formKey``, ``formRefBinding``, ``class``, ``decisionRef``,
  ``resultVariable``, ``mapDecisionResult``
* elements: ``formData/formField``, ``inputOutput/{inputParameter,outputParameter}``,
  ``connector`` (``connectorId`` and its ``inputOutput``), ``in`` and ``out``

Not read by the emitter (still preserved in the IR): ``formRefBinding``, ``formField``
default values, ``connectorId`` and ``mapDecisionResult``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ...processes.intermediate_model.extensions import ExtensionElement, Extensions

CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn"

JUEL_WRAPPER_RE = re.compile(r"^\s*\$\{(.*)\}\s*$", re.DOTALL)
JUEL_INTERPOLATION_RE = re.compile(r"\$\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}")


def strip_juel(expr: Optional[str]) -> Optional[str]:
    """Removes the ``${...}`` wrapper of a JUEL expression."""
    if expr is None:
        return None
    cleaned = expr.strip()
    match = JUEL_WRAPPER_RE.match(cleaned)
    return match.group(1).strip() if match else cleaned


@dataclass
class FormField:
    id: str
    field_type: str = "string"
    label: str = ""
    default_value: Optional[str] = None


@dataclass
class HttpConnector:
    connector_id: str = "http-connector"
    method: str = "GET"
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    payload_raw: Optional[str] = None
    payload_variables: Dict[str, str] = field(default_factory=dict)
    output_parameters: Dict[str, str] = field(default_factory=dict)


@dataclass
class VariableMapping:
    source: str
    target: str
    is_expression: bool = False
    all_variables: bool = False


def form_ref(extensions: Extensions) -> Optional[str]:
    return extensions.attribute(CAMUNDA_NS, "formRef") or extensions.attribute(CAMUNDA_NS, "formKey")


def form_fields(extensions: Extensions) -> List[FormField]:
    fields: List[FormField] = []
    for form_data in extensions.find_all(CAMUNDA_NS, "formData"):
        for xml_field in form_data.find_children(CAMUNDA_NS, "formField"):
            field_id = xml_field.attribute(None, "id")
            if not field_id:
                continue
            fields.append(
                FormField(
                    id=field_id,
                    field_type=xml_field.attribute(None, "type") or "string",
                    label=(xml_field.attribute(None, "label") or "").strip(),
                    default_value=xml_field.attribute(None, "defaultValue"),
                )
            )
    return fields


def delegate_class(extensions: Extensions) -> Optional[str]:
    return extensions.attribute(CAMUNDA_NS, "class")


def decision_ref(extensions: Extensions) -> Optional[str]:
    return extensions.attribute(CAMUNDA_NS, "decisionRef")


def result_variable(extensions: Extensions) -> Optional[str]:
    return extensions.attribute(CAMUNDA_NS, "resultVariable")


def input_output_parameters(extensions: Extensions) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Node-level ``camunda:inputOutput`` parameters as ``(inputs, outputs)``."""
    inputs: Dict[str, str] = {}
    outputs: Dict[str, str] = {}
    for block in extensions.find_all(CAMUNDA_NS, "inputOutput"):
        for param in block.find_children(CAMUNDA_NS, "inputParameter"):
            name = param.attribute(None, "name")
            if name and param.text:
                inputs[name] = strip_juel(param.text) or ""
        for param in block.find_children(CAMUNDA_NS, "outputParameter"):
            name = param.attribute(None, "name")
            if name and param.text:
                outputs[name] = strip_juel(param.text) or ""
    return inputs, outputs


def http_connector(extensions: Extensions) -> Optional[HttpConnector]:
    connector = extensions.find(CAMUNDA_NS, "connector")
    if connector is None:
        return None
    connector_id_el = connector.find_child(CAMUNDA_NS, "connectorId")
    spec = HttpConnector()
    if connector_id_el is not None and connector_id_el.text:
        spec.connector_id = connector_id_el.text.strip()
    io_block = connector.find_child(CAMUNDA_NS, "inputOutput")
    if io_block is None:
        return spec

    for param in io_block.find_children(CAMUNDA_NS, "inputParameter"):
        name = param.attribute(None, "name")
        if name == "method" and param.text:
            spec.method = param.text.strip().upper()
        elif name == "url" and param.text:
            spec.url = param.text.strip()
        elif name == "headers":
            for entry in _find_entries(param):
                key = entry.attribute(None, "key")
                if key and entry.text:
                    spec.headers[key] = entry.text.strip()
        elif name == "payload" and param.text:
            spec.payload_raw = param.text.strip()
            for variable in JUEL_INTERPOLATION_RE.findall(spec.payload_raw):
                spec.payload_variables[variable] = variable
    for param in io_block.find_children(CAMUNDA_NS, "outputParameter"):
        name = param.attribute(None, "name")
        if name and param.text:
            spec.output_parameters[name] = strip_juel(param.text) or "response"
    return spec


def _find_entries(parameter: ExtensionElement) -> List[ExtensionElement]:
    entries: List[ExtensionElement] = []
    for node in parameter.iter_tree():
        if node.is_a(CAMUNDA_NS, "map"):
            entries.extend(node.find_children(CAMUNDA_NS, "entry"))
    return entries


def call_activity_mappings(extensions: Extensions) -> Tuple[List[VariableMapping], List[VariableMapping]]:
    """``camunda:in`` and ``camunda:out`` mappings of a call activity as ``(inputs, outputs)``."""
    return (
        _mappings(extensions.find_all(CAMUNDA_NS, "in")),
        _mappings(extensions.find_all(CAMUNDA_NS, "out")),
    )


def _mappings(elements: List[ExtensionElement]) -> List[VariableMapping]:
    mappings: List[VariableMapping] = []
    for element in elements:
        if element.attribute(None, "variables") == "all":
            mappings.append(VariableMapping(source="all", target="all", all_variables=True))
            continue
        source_expression = element.attribute(None, "sourceExpression")
        source = element.attribute(None, "source") or source_expression or ""
        if not source:
            continue
        mappings.append(
            VariableMapping(
                source=strip_juel(source) or source,
                target=element.attribute(None, "target") or source,
                is_expression=source_expression is not None,
            )
        )
    return mappings
