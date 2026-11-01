"""Data structures for the Intermediate Process Model (extracted from BPMN 2.0 / Camunda XML)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(str, Enum):
    START_EVENT = "start_event"
    END_EVENT = "end_event"
    USER_TASK = "user_task"
    SERVICE_TASK = "service_task"
    SCRIPT_TASK = "script_task"
    MANUAL_TASK = "manual_task"
    BUSINESS_RULE_TASK = "business_rule_task"
    CALL_ACTIVITY = "call_activity"
    EXCLUSIVE_GATEWAY = "exclusive_gateway"
    PARALLEL_GATEWAY = "parallel_gateway"
    INCLUSIVE_GATEWAY = "inclusive_gateway"


class GatewayDirection(str, Enum):
    DIVERGING = "diverging"    # Split (1 incoming, >1 outgoing)
    CONVERGING = "converging"  # Join (>1 incoming, 1 outgoing)
    MIXED = "mixed"            # >1 incoming and >1 outgoing
    PASS_THROUGH = "pass_through"


@dataclass
class FormFieldSpec:
    """Represents a Camunda form field (<camunda:formField>)."""
    id: str
    field_type: str = "string"  # boolean, long, integer, string, enum, date
    label: str = ""
    default_value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.field_type,
            "label": self.label,
            "default_value": self.default_value,
        }


@dataclass
class HttpConnectorSpec:
    """Represents a Camunda HTTP Connector (<camunda:connectorId>http-connector</camunda:connectorId>)."""
    connector_id: str = "http-connector"
    method: str = "GET"
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    payload_raw: Optional[str] = None
    payload_variables: Dict[str, str] = field(default_factory=dict)
    output_parameters: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "method": self.method,
            "url": self.url,
            "headers": dict(self.headers),
            "payload_raw": self.payload_raw,
            "payload_variables": dict(self.payload_variables),
            "output_parameters": dict(self.output_parameters),
        }


@dataclass
class VariableMappingSpec:
    """Represents an input/output parameter or CallActivity variable mapping."""
    source: str
    target: str
    is_expression: bool = False
    all_variables: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "is_expression": self.is_expression,
            "all_variables": self.all_variables,
        }


@dataclass
class FlowNode:
    """Base class for all BPMN flow nodes in the intermediate model."""
    id: str
    name: str
    node_type: NodeType
    lane: Optional[str] = None
    incoming_flows: List[str] = field(default_factory=list)
    outgoing_flows: List[str] = field(default_factory=list)
    input_parameters: Dict[str, str] = field(default_factory=dict)
    output_parameters: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "node_type": self.node_type.value,
            "lane": self.lane,
            "incoming_flows": list(self.incoming_flows),
            "outgoing_flows": list(self.outgoing_flows),
            "input_parameters": dict(self.input_parameters),
            "output_parameters": dict(self.output_parameters),
        }


@dataclass
class StartEventNode(FlowNode):
    form_ref: Optional[str] = None
    form_fields: List[FormFieldSpec] = field(default_factory=list)

    def __init__(
        self,
        id: str,
        name: str = "",
        lane: Optional[str] = None,
        form_ref: Optional[str] = None,
        form_fields: Optional[List[FormFieldSpec]] = None,
        **kwargs: Any,
    ):
        super().__init__(id=id, name=name or id, node_type=NodeType.START_EVENT, lane=lane, **kwargs)
        self.form_ref = form_ref
        self.form_fields = form_fields or []

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["form_ref"] = self.form_ref
        base["form_fields"] = [f.to_dict() for f in self.form_fields]
        return base


@dataclass
class EndEventNode(FlowNode):
    def __init__(self, id: str, name: str = "", lane: Optional[str] = None, **kwargs: Any):
        super().__init__(id=id, name=name or id, node_type=NodeType.END_EVENT, lane=lane, **kwargs)


@dataclass
class UserTaskNode(FlowNode):
    form_ref: Optional[str] = None
    form_ref_binding: Optional[str] = None
    form_fields: List[FormFieldSpec] = field(default_factory=list)

    def __init__(
        self,
        id: str,
        name: str = "",
        lane: Optional[str] = None,
        form_ref: Optional[str] = None,
        form_ref_binding: Optional[str] = None,
        form_fields: Optional[List[FormFieldSpec]] = None,
        **kwargs: Any,
    ):
        super().__init__(id=id, name=name or id, node_type=NodeType.USER_TASK, lane=lane, **kwargs)
        self.form_ref = form_ref
        self.form_ref_binding = form_ref_binding
        self.form_fields = form_fields or []

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "form_ref": self.form_ref,
                "form_ref_binding": self.form_ref_binding,
                "form_fields": [f.to_dict() for f in self.form_fields],
            }
        )
        return base


@dataclass
class ServiceTaskNode(FlowNode):
    delegate_class: Optional[str] = None
    http_connector: Optional[HttpConnectorSpec] = None

    def __init__(
        self,
        id: str,
        name: str = "",
        lane: Optional[str] = None,
        delegate_class: Optional[str] = None,
        http_connector: Optional[HttpConnectorSpec] = None,
        **kwargs: Any,
    ):
        super().__init__(id=id, name=name or id, node_type=NodeType.SERVICE_TASK, lane=lane, **kwargs)
        self.delegate_class = delegate_class
        self.http_connector = http_connector

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["delegate_class"] = self.delegate_class
        base["http_connector"] = self.http_connector.to_dict() if self.http_connector else None
        return base


@dataclass
class ScriptTaskNode(FlowNode):
    script_format: str = "python"
    script: str = ""

    def __init__(
        self,
        id: str,
        name: str = "",
        lane: Optional[str] = None,
        script_format: str = "python",
        script: str = "",
        **kwargs: Any,
    ):
        super().__init__(id=id, name=name or id, node_type=NodeType.SCRIPT_TASK, lane=lane, **kwargs)
        self.script_format = script_format
        self.script = script

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["script_format"] = self.script_format
        base["script"] = self.script
        return base


@dataclass
class ManualTaskNode(FlowNode):
    def __init__(self, id: str, name: str = "", lane: Optional[str] = None, **kwargs: Any):
        super().__init__(id=id, name=name or id, node_type=NodeType.MANUAL_TASK, lane=lane, **kwargs)


@dataclass
class BusinessRuleTaskNode(FlowNode):
    """Represents a BPMN BusinessRuleTask (extensible hook for future DMN integration)."""
    decision_ref: Optional[str] = None
    result_variable: Optional[str] = None
    map_decision_result: str = "singleEntry"

    def __init__(
        self,
        id: str,
        name: str = "",
        lane: Optional[str] = None,
        decision_ref: Optional[str] = None,
        result_variable: Optional[str] = None,
        map_decision_result: str = "singleEntry",
        **kwargs: Any,
    ):
        super().__init__(id=id, name=name or id, node_type=NodeType.BUSINESS_RULE_TASK, lane=lane, **kwargs)
        self.decision_ref = decision_ref
        self.result_variable = result_variable
        self.map_decision_result = map_decision_result

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "decision_ref": self.decision_ref,
                "result_variable": self.result_variable,
                "map_decision_result": self.map_decision_result,
                "dmn_mode": "mock_stub",
            }
        )
        return base


@dataclass
class CallActivityNode(FlowNode):
    called_element: str = ""
    in_mappings: List[VariableMappingSpec] = field(default_factory=list)
    out_mappings: List[VariableMappingSpec] = field(default_factory=list)

    def __init__(
        self,
        id: str,
        name: str = "",
        lane: Optional[str] = None,
        called_element: str = "",
        in_mappings: Optional[List[VariableMappingSpec]] = None,
        out_mappings: Optional[List[VariableMappingSpec]] = None,
        **kwargs: Any,
    ):
        super().__init__(id=id, name=name or id, node_type=NodeType.CALL_ACTIVITY, lane=lane, **kwargs)
        self.called_element = called_element
        self.in_mappings = in_mappings or []
        self.out_mappings = out_mappings or []

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "called_element": self.called_element,
                "in_mappings": [m.to_dict() for m in self.in_mappings],
                "out_mappings": [m.to_dict() for m in self.out_mappings],
            }
        )
        return base


@dataclass
class GatewayNode(FlowNode):
    default_flow_id: Optional[str] = None

    def __init__(
        self,
        id: str,
        name: str = "",
        gateway_type: NodeType = NodeType.EXCLUSIVE_GATEWAY,
        lane: Optional[str] = None,
        default_flow_id: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(id=id, name=name or id, node_type=gateway_type, lane=lane, **kwargs)
        self.default_flow_id = default_flow_id

    @property
    def direction(self) -> GatewayDirection:
        in_count = len(self.incoming_flows)
        out_count = len(self.outgoing_flows)
        if in_count <= 1 and out_count > 1:
            return GatewayDirection.DIVERGING
        if in_count > 1 and out_count <= 1:
            return GatewayDirection.CONVERGING
        if in_count > 1 and out_count > 1:
            return GatewayDirection.MIXED
        return GatewayDirection.PASS_THROUGH

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["default_flow_id"] = self.default_flow_id
        base["direction"] = self.direction.value
        return base


@dataclass
class SequenceFlowEdge:
    id: str
    source_ref: str
    target_ref: str
    name: str = ""
    condition_expression: Optional[str] = None
    is_default: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "name": self.name,
            "condition_expression": self.condition_expression,
            "is_default": self.is_default,
        }


@dataclass
class LaneModel:
    id: str
    name: str
    node_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "node_ids": list(self.node_ids),
        }


@dataclass
class ProcessGraph:
    """Complete Intermediate Model of a single BPMN Process."""
    process_id: str
    name: str
    is_executable: bool = True
    participant_name: Optional[str] = None
    lanes: List[LaneModel] = field(default_factory=list)
    nodes: Dict[str, FlowNode] = field(default_factory=dict)
    edges: Dict[str, SequenceFlowEdge] = field(default_factory=dict)
    warnings: List[Dict[str, str]] = field(default_factory=list)

    @property
    def start_nodes(self) -> List[StartEventNode]:
        return [n for n in self.nodes.values() if isinstance(n, StartEventNode)]

    @property
    def end_nodes(self) -> List[EndEventNode]:
        return [n for n in self.nodes.values() if isinstance(n, EndEventNode)]

    def get_outgoing_edges(self, node_id: str) -> List[SequenceFlowEdge]:
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.edges[fid] for fid in node.outgoing_flows if fid in self.edges]

    def get_incoming_edges(self, node_id: str) -> List[SequenceFlowEdge]:
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.edges[fid] for fid in node.incoming_flows if fid in self.edges]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "process_id": self.process_id,
            "name": self.name,
            "is_executable": self.is_executable,
            "participant_name": self.participant_name,
            "lanes": [l.to_dict() for l in self.lanes],
            "start_nodes": [n.id for n in self.start_nodes],
            "end_nodes": [n.id for n in self.end_nodes],
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "edges": {eid: edge.to_dict() for eid, edge in self.edges.items()},
            "warnings": list(self.warnings),
        }

