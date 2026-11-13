"""JSON (camelCase) representation of an imported BPMN document for the import-only endpoint.

This is the API view of the IR. It is explicit on purpose: data keys that come from the XML
(extension attribute names such as ``{namespace}local``) must be kept exactly as they are, so a
generic snake_case to camelCase conversion of the IR's ``to_dict`` output would be wrong.
Nothing is dropped: extensions, unrecognized content and unsupported nodes are all included.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .intermediate_model.diagnostics import ImportResult
from .intermediate_model.extensions import ExtensionElement, Extensions
from .intermediate_model.models import (
    BpmnDocument,
    CallActivityNode,
    FlowNode,
    Lane,
    LaneSet,
    Participant,
    ProcessGraph,
    ScriptTaskNode,
    SequenceFlowEdge,
    UnsupportedNode,
)


def build_import_response(result: ImportResult) -> Dict[str, Any]:
    """Body of a successful import: ``supported`` (analysis can run), all diagnostics, the document."""
    assert result.document is not None, "build_import_response requires an import without errors"
    return {
        "supported": result.analysis_supported,
        "diagnostics": [d.to_dict() for d in result.diagnostics],
        "document": document_to_json(result.document),
    }


def document_to_json(document: BpmnDocument) -> Dict[str, Any]:
    return {
        "definitionsId": document.definitions_id,
        "name": document.name,
        "targetNamespace": document.target_namespace,
        "sourceLine": document.source_line,
        "participants": [_participant(p) for p in document.participants],
        "processes": [_process(p) for p in document.processes],
        "extensions": _extensions(document.extensions),
        "unrecognized": _generic_list(document.unrecognized),
    }


def _process(process: ProcessGraph) -> Dict[str, Any]:
    return {
        "id": process.process_id,
        "name": process.name,
        "isExecutable": process.is_executable,
        "documentation": process.documentation,
        "sourceLine": process.source_line,
        "participant": _participant(process.participant) if process.participant else None,
        "laneSets": [_lane_set(ls) for ls in process.lane_sets],
        "nodes": [_node(n) for n in process.nodes.values()],
        "sequenceFlows": [_flow(e) for e in process.edges.values()],
        "extensions": _extensions(process.extensions),
        "unrecognized": _generic_list(process.unrecognized),
    }


def _participant(participant: Participant) -> Dict[str, Any]:
    return {
        "id": participant.id,
        "name": participant.name,
        "processRef": participant.process_ref,
        "sourceLine": participant.source_line,
    }


def _lane_set(lane_set: LaneSet) -> Dict[str, Any]:
    return {"id": lane_set.id, "name": lane_set.name, "lanes": [_lane(lane) for lane in lane_set.lanes]}


def _lane(lane: Lane) -> Dict[str, Any]:
    return {
        "id": lane.id,
        "name": lane.name,
        "flowNodeRefs": list(lane.flow_node_refs),
        "childLaneSet": _lane_set(lane.child_lane_set) if lane.child_lane_set else None,
        "sourceLine": lane.source_line,
    }


def _node(node: FlowNode) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "id": node.id,
        "name": node.name,
        "bpmnType": node.bpmn_type,
        "nodeType": node.node_type.value,
        "support": node.support.value,
        "documentation": node.documentation,
        "defaultFlowId": node.default_flow_id,
        "incoming": list(node.incoming_flows),
        "outgoing": list(node.outgoing_flows),
        "sourceLine": node.source_line,
        "extensions": _extensions(node.extensions),
        "unrecognized": _generic_list(node.unrecognized),
    }
    if isinstance(node, ScriptTaskNode):
        body["scriptFormat"] = node.script_format
        body["script"] = node.script
    elif isinstance(node, CallActivityNode):
        body["calledElement"] = node.called_element
    elif isinstance(node, UnsupportedNode):
        body["source"] = _generic(node.source) if node.source else None
    return body


def _flow(edge: SequenceFlowEdge) -> Dict[str, Any]:
    condition = edge.condition
    return {
        "id": edge.id,
        "sourceRef": edge.source_ref,
        "targetRef": edge.target_ref,
        "name": edge.name,
        "condition": (
            {"text": condition.text, "language": condition.language, "xsiType": condition.xsi_type}
            if condition
            else None
        ),
        "isDefault": edge.is_default,
        "documentation": edge.documentation,
        "sourceLine": edge.source_line,
        "extensions": _extensions(edge.extensions),
        "unrecognized": _generic_list(edge.unrecognized),
    }


def _extensions(extensions: Extensions) -> Dict[str, Any]:
    return {"attributes": dict(extensions.attributes), "elements": _generic_list(extensions.elements)}


def _generic_list(elements: List[ExtensionElement]) -> List[Dict[str, Any]]:
    return [_generic(e) for e in elements]


def _generic(element: Optional[ExtensionElement]) -> Dict[str, Any]:
    assert element is not None
    return {
        "namespaceUri": element.namespace_uri,
        "localName": element.local_name,
        "attributes": dict(element.attributes),
        "text": element.text,
        "children": _generic_list(element.children),
    }
