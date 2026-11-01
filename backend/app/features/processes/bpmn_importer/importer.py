"""Refactored BPMN 2.0 & Camunda XML Importer based on SpiffWorkflow's parser architecture.

Supports standard library `xml.etree.ElementTree` natively (100% vanilla Python) and optionally
uses `lxml.etree` for full XSD validation when `lxml` is installed in the environment.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
from xml.etree.ElementTree import Element, ParseError

try:
    from lxml import etree as lxml_etree  # type: ignore[import-not-found]
    HAS_LXML = True
except ImportError:
    lxml_etree = None
    HAS_LXML = False

from ..intermediate_model.models import (
    BusinessRuleTaskNode,
    CallActivityNode,
    EndEventNode,
    FlowNode,
    FormFieldSpec,
    GatewayNode,
    HttpConnectorSpec,
    LaneModel,
    ManualTaskNode,
    NodeType,
    ProcessGraph,
    ScriptTaskNode,
    SequenceFlowEdge,
    ServiceTaskNode,
    StartEventNode,
    UserTaskNode,
    VariableMappingSpec,
)

BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

DEFAULT_NSMAP = {
    "bpmn": BPMN_MODEL_NS,
    "bpmndi": BPMNDI_NS,
    "dc": DC_NS,
    "di": DI_NS,
    "camunda": CAMUNDA_NS,
    "xsi": XSI_NS,
}

SPIFF_XSD_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "..",
        "SpiffWorkflow",
        "SpiffWorkflow",
        "bpmn",
        "parser",
        "schema",
        "BPMN20.xsd",
    )
)

JUEL_WRAPPER_RE = re.compile(r"^\s*\$\{(.*)\}\s*$", re.DOTALL)
JUEL_INTERPOLATION_RE = re.compile(r"\$\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}")


class BpmnImportValidationError(Exception):
    """Raised when the uploaded BPMN XML fails structural or XSD validation."""

    def __init__(self, message: str, line_number: Optional[int] = None, node_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.line_number = line_number
        self.node_id = node_id

    def to_dict(self) -> Dict[str, Optional[str | int]]:
        return {
            "message": self.message,
            "line_number": self.line_number,
            "node_id": self.node_id,
        }


def local_tag_name(tag: str) -> str:
    """Extracts the local XML tag name without namespace URI."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def strip_juel(expr: Optional[str]) -> Optional[str]:
    """Strips `${...}` wrapper from Camunda/JUEL expressions."""
    if expr is None:
        return None
    cleaned = expr.strip()
    match = JUEL_WRAPPER_RE.match(cleaned)
    if match:
        return match.group(1).strip()
    return cleaned


class BpmnXmlValidator:
    """Refactored from SpiffWorkflow's BpmnValidator to validate BPMN 2.0 XML documents."""

    def __init__(self, xsd_path: str = SPIFF_XSD_PATH):
        self.xsd_path = xsd_path
        self.validator = None
        if HAS_LXML and os.path.exists(xsd_path):
            with open(xsd_path, "rb") as xsd_file:
                schema_doc = lxml_etree.parse(xsd_file)
                self.validator = lxml_etree.XMLSchema(schema_doc)

    def validate_xml_tree(self, root: Element, raw_bytes: Optional[bytes] = None) -> List[Dict[str, str]]:
        """Validates core BPMN 2.0 structure and returns any non-fatal schema warnings."""
        warnings: List[Dict[str, str]] = []
        if local_tag_name(root.tag) != "definitions":
            raise BpmnImportValidationError(
                f"Root XML element must be 'bpmn:definitions', got '{root.tag}'"
            )

        processes = root.findall(".//bpmn:process", namespaces=DEFAULT_NSMAP)
        if not processes:
            raise BpmnImportValidationError(
                "No <bpmn:process> element found in the BPMN document."
            )

        if self.validator is not None and raw_bytes is not None and HAS_LXML:
            try:
                lxml_root = lxml_etree.fromstring(raw_bytes)
                self.validator.assertValid(lxml_root)
            except Exception as err:
                last_err = self.validator.error_log.last_error
                msg = last_err.message if last_err else str(err)
                if "camunda" not in msg and "modeler" not in msg:
                    warnings.append(
                        {
                            "type": "XSD_VALIDATION_NOTICE",
                            "message": msg,
                            "line": str(last_err.line if last_err else 0),
                        }
                    )
        return warnings


class BpmnImporter:
    """Parses a single BPMN 2.0 / Camunda XML document into a normalized ProcessGraph."""

    def __init__(self, validate_xsd: bool = True):
        self.validator = BpmnXmlValidator() if validate_xsd else None

    def parse_string(self, xml_content: str | bytes, filename: Optional[str] = None) -> ProcessGraph:
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
        else:
            xml_bytes = xml_content

        try:
            root = ET.fromstring(xml_bytes)
        except ParseError as exc:
            line_num = exc.position[0] if hasattr(exc, "position") and exc.position else None
            raise BpmnImportValidationError(
                f"Malformed XML document{f' ({filename})' if filename else ''}: {exc}",
                line_number=line_num,
            ) from exc

        return self.parse_tree(root, raw_bytes=xml_bytes)

    def parse_file(self, file_path: str) -> ProcessGraph:
        with open(file_path, "rb") as f:
            return self.parse_string(f.read(), filename=os.path.basename(file_path))

    def parse_tree(self, root: Element, raw_bytes: Optional[bytes] = None) -> ProcessGraph:
        warnings: List[Dict[str, str]] = []
        if self.validator:
            warnings.extend(self.validator.validate_xml_tree(root, raw_bytes=raw_bytes))

        processes = root.findall(".//bpmn:process", namespaces=DEFAULT_NSMAP)
        if not processes:
            raise BpmnImportValidationError("No <bpmn:process> element found in the BPMN document.")

        target_process = None
        for proc in processes:
            if proc.get("isExecutable", "true").lower() == "true":
                target_process = proc
                break
        if target_process is None:
            target_process = processes[0]

        process_id = target_process.get("id")
        if not process_id:
            raise BpmnImportValidationError("The <bpmn:process> element is missing a required 'id' attribute.")

        process_name = target_process.get("name") or process_id
        is_executable = target_process.get("isExecutable", "true").lower() == "true"

        participant_name = self._extract_participant_name(root, process_id)
        lanes, node_to_lane = self._extract_lanes(target_process)

        graph = ProcessGraph(
            process_id=process_id,
            name=process_name,
            is_executable=is_executable,
            participant_name=participant_name,
            lanes=lanes,
            warnings=warnings,
        )

        # Index nodes and sequence flows (inspired by SpiffWorkflow's ProcessParser._index_process_nodes)
        for child in list(target_process):
            local_tag = local_tag_name(child.tag)
            if local_tag == "sequenceFlow":
                edge = self._parse_sequence_flow(child)
                graph.edges[edge.id] = edge
            else:
                node = self._parse_flow_node(child, local_tag, node_to_lane)
                if node is not None:
                    graph.nodes[node.id] = node

        self._connect_graph_edges(graph)
        return graph

    def _extract_participant_name(self, root: Element, process_id: str) -> Optional[str]:
        participants = root.findall(".//bpmn:collaboration/bpmn:participant", namespaces=DEFAULT_NSMAP)
        for p in participants:
            if p.get("processRef") == process_id:
                return p.get("name")
        return None

    def _extract_lanes(self, process_node: Element) -> Tuple[List[LaneModel], Dict[str, str]]:
        lanes: List[LaneModel] = []
        node_to_lane: Dict[str, str] = {}
        lane_elements = process_node.findall(".//bpmn:laneSet/bpmn:lane", namespaces=DEFAULT_NSMAP)
        for lane_el in lane_elements:
            lane_id = lane_el.get("id", "")
            lane_name = lane_el.get("name") or lane_id
            refs = [
                ref.text.strip()
                for ref in lane_el.findall("./bpmn:flowNodeRef", namespaces=DEFAULT_NSMAP)
                if ref.text and ref.text.strip()
            ]
            lanes.append(LaneModel(id=lane_id, name=lane_name, node_ids=refs))
            for nid in refs:
                node_to_lane[nid] = lane_name
        return lanes, node_to_lane

    def _parse_sequence_flow(self, elem: Element) -> SequenceFlowEdge:
        flow_id = elem.get("id")
        source_ref = elem.get("sourceRef")
        target_ref = elem.get("targetRef")
        if not flow_id or not source_ref or not target_ref:
            raise BpmnImportValidationError(
                "A <bpmn:sequenceFlow> is missing id, sourceRef, or targetRef."
            )
        name = elem.get("name") or ""
        cond_nodes = elem.findall("./bpmn:conditionExpression", namespaces=DEFAULT_NSMAP)
        condition_expr: Optional[str] = None
        if cond_nodes and cond_nodes[0].text:
            condition_expr = strip_juel(cond_nodes[0].text)

        return SequenceFlowEdge(
            id=flow_id,
            source_ref=source_ref,
            target_ref=target_ref,
            name=name,
            condition_expression=condition_expr,
            is_default=False,
        )

    def _parse_flow_node(
        self, elem: Element, local_tag: str, node_to_lane: Dict[str, str]
    ) -> Optional[FlowNode]:
        node_id = elem.get("id")
        if not node_id:
            return None
        name = elem.get("name") or node_id
        lane = node_to_lane.get(node_id)
        in_params, out_params = self._parse_camunda_io(elem)

        common_kwargs = {
            "id": node_id,
            "name": name,
            "lane": lane,
            "input_parameters": in_params,
            "output_parameters": out_params,
        }

        if local_tag == "startEvent":
            form_ref = elem.get(f"{{{CAMUNDA_NS}}}formRef") or elem.get(f"{{{CAMUNDA_NS}}}formKey")
            form_fields = self._parse_camunda_form_fields(elem)
            return StartEventNode(form_ref=form_ref, form_fields=form_fields, **common_kwargs)

        if local_tag == "endEvent":
            return EndEventNode(**common_kwargs)

        if local_tag == "userTask":
            form_ref = elem.get(f"{{{CAMUNDA_NS}}}formRef") or elem.get(f"{{{CAMUNDA_NS}}}formKey")
            form_ref_binding = elem.get(f"{{{CAMUNDA_NS}}}formRefBinding")
            form_fields = self._parse_camunda_form_fields(elem)
            return UserTaskNode(
                form_ref=form_ref,
                form_ref_binding=form_ref_binding,
                form_fields=form_fields,
                **common_kwargs,
            )

        if local_tag in ("serviceTask", "task", "sendTask", "receiveTask"):
            delegate_class = elem.get(f"{{{CAMUNDA_NS}}}class")
            http_connector = self._parse_http_connector(elem)
            return ServiceTaskNode(
                delegate_class=delegate_class,
                http_connector=http_connector,
                **common_kwargs,
            )

        if local_tag == "scriptTask":
            script_format = elem.get("scriptFormat", "python")
            script_nodes = elem.findall("./bpmn:script", namespaces=DEFAULT_NSMAP)
            script_text = script_nodes[0].text.strip() if script_nodes and script_nodes[0].text else ""
            return ScriptTaskNode(script_format=script_format, script=script_text, **common_kwargs)

        if local_tag == "manualTask":
            return ManualTaskNode(**common_kwargs)

        if local_tag == "businessRuleTask":
            decision_ref = elem.get(f"{{{CAMUNDA_NS}}}decisionRef")
            result_var = elem.get(f"{{{CAMUNDA_NS}}}resultVariable")
            map_result = elem.get(f"{{{CAMUNDA_NS}}}mapDecisionResult", "singleEntry")
            return BusinessRuleTaskNode(
                decision_ref=decision_ref,
                result_variable=result_var,
                map_decision_result=map_result,
                **common_kwargs,
            )

        if local_tag == "callActivity":
            called_element = elem.get("calledElement", "")
            in_maps, out_maps = self._parse_call_activity_mappings(elem)
            return CallActivityNode(
                called_element=called_element,
                in_mappings=in_maps,
                out_mappings=out_maps,
                **common_kwargs,
            )

        if local_tag == "exclusiveGateway":
            default_flow = elem.get("default")
            return GatewayNode(
                gateway_type=NodeType.EXCLUSIVE_GATEWAY,
                default_flow_id=default_flow,
                **common_kwargs,
            )

        if local_tag == "parallelGateway":
            return GatewayNode(
                gateway_type=NodeType.PARALLEL_GATEWAY,
                default_flow_id=None,
                **common_kwargs,
            )

        if local_tag == "inclusiveGateway":
            default_flow = elem.get("default")
            return GatewayNode(
                gateway_type=NodeType.INCLUSIVE_GATEWAY,
                default_flow_id=default_flow,
                **common_kwargs,
            )

        return None

    def _parse_camunda_form_fields(self, elem: Element) -> List[FormFieldSpec]:
        fields: List[FormFieldSpec] = []
        xml_fields = elem.findall(".//camunda:formData/camunda:formField", namespaces=DEFAULT_NSMAP)
        for xf in xml_fields:
            fid = xf.get("id")
            if not fid:
                continue
            ftype = xf.get("type", "string")
            label = (xf.get("label") or "").strip()
            default_val = xf.get("defaultValue")
            fields.append(FormFieldSpec(id=fid, field_type=ftype, label=label, default_value=default_val))
        return fields

    def _parse_camunda_io(self, elem: Element) -> Tuple[Dict[str, str], Dict[str, str]]:
        in_params: Dict[str, str] = {}
        out_params: Dict[str, str] = {}
        io_blocks = elem.findall("./bpmn:extensionElements/camunda:inputOutput", namespaces=DEFAULT_NSMAP)
        for io in io_blocks:
            for ip in io.findall("./camunda:inputParameter", namespaces=DEFAULT_NSMAP):
                pname = ip.get("name")
                if pname and ip.text:
                    in_params[pname] = strip_juel(ip.text) or ""
            for op in io.findall("./camunda:outputParameter", namespaces=DEFAULT_NSMAP):
                pname = op.get("name")
                if pname and op.text:
                    out_params[pname] = strip_juel(op.text) or ""
        return in_params, out_params

    def _parse_http_connector(self, elem: Element) -> Optional[HttpConnectorSpec]:
        connectors = elem.findall("./bpmn:extensionElements/camunda:connector", namespaces=DEFAULT_NSMAP)
        if not connectors:
            return None
        conn = connectors[0]
        cid_nodes = conn.findall("./camunda:connectorId", namespaces=DEFAULT_NSMAP)
        connector_id = cid_nodes[0].text.strip() if cid_nodes and cid_nodes[0].text else "http-connector"

        method = "GET"
        url = ""
        headers: Dict[str, str] = {}
        payload_raw: Optional[str] = None
        payload_variables: Dict[str, str] = {}
        output_parameters: Dict[str, str] = {}

        for ip in conn.findall("./camunda:inputOutput/camunda:inputParameter", namespaces=DEFAULT_NSMAP):
            pname = ip.get("name")
            if pname == "method" and ip.text:
                method = ip.text.strip().upper()
            elif pname == "url" and ip.text:
                url = ip.text.strip()
            elif pname == "headers":
                for entry in ip.findall(".//camunda:map/camunda:entry", namespaces=DEFAULT_NSMAP):
                    key = entry.get("key")
                    if key and entry.text:
                        headers[key] = entry.text.strip()
            elif pname == "payload" and ip.text:
                payload_raw = ip.text.strip()
                for var_match in JUEL_INTERPOLATION_RE.findall(payload_raw):
                    payload_variables[var_match] = var_match

        for op in conn.findall("./camunda:inputOutput/camunda:outputParameter", namespaces=DEFAULT_NSMAP):
            pname = op.get("name")
            if pname and op.text:
                output_parameters[pname] = strip_juel(op.text) or "response"

        return HttpConnectorSpec(
            connector_id=connector_id,
            method=method,
            url=url,
            headers=headers,
            payload_raw=payload_raw,
            payload_variables=payload_variables,
            output_parameters=output_parameters,
        )

    def _parse_call_activity_mappings(
        self, elem: Element
    ) -> Tuple[List[VariableMappingSpec], List[VariableMappingSpec]]:
        in_maps: List[VariableMappingSpec] = []
        out_maps: List[VariableMappingSpec] = []

        for in_el in elem.findall("./bpmn:extensionElements/camunda:in", namespaces=DEFAULT_NSMAP):
            if in_el.get("variables") == "all":
                in_maps.append(VariableMappingSpec(source="all", target="all", all_variables=True))
            else:
                src = in_el.get("source") or in_el.get("sourceExpression") or ""
                tgt = in_el.get("target") or src
                if src:
                    in_maps.append(
                        VariableMappingSpec(
                            source=strip_juel(src) or src,
                            target=tgt,
                            is_expression=in_el.get("sourceExpression") is not None,
                        )
                    )

        for out_el in elem.findall("./bpmn:extensionElements/camunda:out", namespaces=DEFAULT_NSMAP):
            if out_el.get("variables") == "all":
                out_maps.append(VariableMappingSpec(source="all", target="all", all_variables=True))
            else:
                src = out_el.get("source") or out_el.get("sourceExpression") or ""
                tgt = out_el.get("target") or src
                if src:
                    out_maps.append(
                        VariableMappingSpec(
                            source=strip_juel(src) or src,
                            target=tgt,
                            is_expression=out_el.get("sourceExpression") is not None,
                        )
                    )

        return in_maps, out_maps

    def _connect_graph_edges(self, graph: ProcessGraph) -> None:
        for edge_id, edge in graph.edges.items():
            src_node = graph.nodes.get(edge.source_ref)
            tgt_node = graph.nodes.get(edge.target_ref)
            if src_node is None:
                raise BpmnImportValidationError(
                    f"SequenceFlow '{edge_id}' references unknown sourceRef '{edge.source_ref}'.",
                    node_id=edge_id,
                )
            if tgt_node is None:
                raise BpmnImportValidationError(
                    f"SequenceFlow '{edge_id}' references unknown targetRef '{edge.target_ref}'.",
                    node_id=edge_id,
                )
            src_node.outgoing_flows.append(edge_id)
            tgt_node.incoming_flows.append(edge_id)

            if isinstance(src_node, GatewayNode) and src_node.default_flow_id == edge_id:
                edge.is_default = True

        for node in graph.nodes.values():
            if (
                isinstance(node, GatewayNode)
                and node.node_type in (NodeType.EXCLUSIVE_GATEWAY, NodeType.INCLUSIVE_GATEWAY)
                and len(node.outgoing_flows) > 1
            ):
                out_edges = graph.get_outgoing_edges(node.id)
                has_default = any(e.is_default for e in out_edges)
                unconditional_edges = [e for e in out_edges if not e.condition_expression and not e.is_default]
                if not has_default and len(unconditional_edges) == 1:
                    unconditional_edges[0].is_default = True
                    node.default_flow_id = unconditional_edges[0].id
                elif not has_default:
                    graph.warnings.append(
                        {
                            "node_id": node.id,
                            "type": "MISSING_DEFAULT_FLOW",
                            "message": f"Gateway '{node.name}' ({node.id}) has multiple outgoing flows but no default flow.",
                        }
                    )
