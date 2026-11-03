"""Vendor-neutral Intermediate Model (IR) of BPMN 2.0 processes.

The IR keeps what BPMN 2.0 itself defines (ids, names, element types, sequence flows,
conditions, lanes, script and called-element data) and derived structure (incoming and
outgoing flow ids, default-flow markers). Anything vendor specific lives in each element's
``extensions``. The IR knows nothing about FlowSpec, Ruby, automata or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .extensions import Extensions


class NodeType(str, Enum):
    """Normalized BPMN element types. ``UNSUPPORTED`` nodes keep their original tag in ``bpmn_type``."""

    START_EVENT = "start_event"
    END_EVENT = "end_event"
    TASK = "task"
    USER_TASK = "user_task"
    SERVICE_TASK = "service_task"
    SCRIPT_TASK = "script_task"
    MANUAL_TASK = "manual_task"
    BUSINESS_RULE_TASK = "business_rule_task"
    SEND_TASK = "send_task"
    RECEIVE_TASK = "receive_task"
    CALL_ACTIVITY = "call_activity"
    EXCLUSIVE_GATEWAY = "exclusive_gateway"
    PARALLEL_GATEWAY = "parallel_gateway"
    INCLUSIVE_GATEWAY = "inclusive_gateway"
    UNSUPPORTED = "unsupported"


class SupportLevel(str, Enum):
    """How far FlowRouby can take an imported element."""

    ANALYZABLE = "analyzable"    # understood and usable by formal analysis
    PRESERVED = "preserved"      # imported faithfully, but not analyzable yet
    UNSUPPORTED = "unsupported"  # kept as an opaque node so the graph stays consistent


class GatewayDirection(str, Enum):
    DIVERGING = "diverging"    # Split (1 incoming, >1 outgoing)
    CONVERGING = "converging"  # Join (>1 incoming, 1 outgoing)
    MIXED = "mixed"            # >1 incoming and >1 outgoing
    PASS_THROUGH = "pass_through"


@dataclass(kw_only=True)
class FlowNode:
    """Any BPMN flow node. Original ``id`` and ``name`` are never rewritten."""

    id: str
    node_type: NodeType
    bpmn_type: str  # original local tag name, e.g. "userTask"
    name: Optional[str] = None
    support: SupportLevel = SupportLevel.ANALYZABLE
    documentation: Optional[str] = None
    default_flow_id: Optional[str] = None  # BPMN "default" attribute (activities and gateways)
    extensions: Extensions = field(default_factory=Extensions)
    incoming_flows: List[str] = field(default_factory=list)  # derived from sequence flows
    outgoing_flows: List[str] = field(default_factory=list)  # derived from sequence flows

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "node_type": self.node_type.value,
            "bpmn_type": self.bpmn_type,
            "support": self.support.value,
            "documentation": self.documentation,
            "default_flow_id": self.default_flow_id,
            "incoming_flows": list(self.incoming_flows),
            "outgoing_flows": list(self.outgoing_flows),
            "extensions": self.extensions.to_dict(),
        }


@dataclass(kw_only=True)
class StartEventNode(FlowNode):
    node_type: NodeType = NodeType.START_EVENT
    bpmn_type: str = "startEvent"


@dataclass(kw_only=True)
class EndEventNode(FlowNode):
    node_type: NodeType = NodeType.END_EVENT
    bpmn_type: str = "endEvent"


@dataclass(kw_only=True)
class ScriptTaskNode(FlowNode):
    """Standard BPMN script task data only (``scriptFormat`` attribute and ``<bpmn:script>`` text)."""

    node_type: NodeType = NodeType.SCRIPT_TASK
    bpmn_type: str = "scriptTask"
    script_format: Optional[str] = None
    script: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({"script_format": self.script_format, "script": self.script})
        return base


@dataclass(kw_only=True)
class CallActivityNode(FlowNode):
    node_type: NodeType = NodeType.CALL_ACTIVITY
    bpmn_type: str = "callActivity"
    called_element: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["called_element"] = self.called_element
        return base


@dataclass(kw_only=True)
class GatewayNode(FlowNode):
    @property
    def direction(self) -> GatewayDirection:
        """Derived from the number of incoming and outgoing sequence flows."""
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
        base["direction"] = self.direction.value
        return base


@dataclass
class Condition:
    """A ``<bpmn:conditionExpression>`` exactly as written in the XML."""

    text: str
    language: Optional[str] = None  # the "language" attribute
    xsi_type: Optional[str] = None  # the "xsi:type" attribute

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "language": self.language, "xsi_type": self.xsi_type}


@dataclass
class SequenceFlowEdge:
    id: str
    source_ref: str
    target_ref: str
    name: Optional[str] = None
    condition: Optional[Condition] = None
    is_default: bool = False  # derived: the source node's "default" attribute points to this flow
    documentation: Optional[str] = None
    extensions: Extensions = field(default_factory=Extensions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "name": self.name,
            "condition": self.condition.to_dict() if self.condition else None,
            "is_default": self.is_default,
            "documentation": self.documentation,
            "extensions": self.extensions.to_dict(),
        }


@dataclass
class Lane:
    id: str
    name: Optional[str] = None
    flow_node_refs: List[str] = field(default_factory=list)
    child_lane_set: Optional["LaneSet"] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "flow_node_refs": list(self.flow_node_refs),
            "child_lane_set": self.child_lane_set.to_dict() if self.child_lane_set else None,
        }


@dataclass
class LaneSet:
    id: Optional[str] = None
    name: Optional[str] = None
    lanes: List[Lane] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "lanes": [lane.to_dict() for lane in self.lanes]}


@dataclass
class Participant:
    id: str
    name: Optional[str] = None
    process_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "process_ref": self.process_ref}


@dataclass
class ProcessGraph:
    """One BPMN ``<process>`` as nodes and sequence flows indexed by their original BPMN ids."""

    process_id: str
    name: Optional[str] = None
    is_executable: Optional[bool] = None  # None when the attribute is absent
    participant: Optional[Participant] = None
    lane_sets: List[LaneSet] = field(default_factory=list)
    nodes: Dict[str, FlowNode] = field(default_factory=dict)
    edges: Dict[str, SequenceFlowEdge] = field(default_factory=dict)
    documentation: Optional[str] = None
    extensions: Extensions = field(default_factory=Extensions)

    @property
    def participant_name(self) -> Optional[str]:
        return self.participant.name if self.participant else None

    @property
    def start_nodes(self) -> List[StartEventNode]:
        return [n for n in self.nodes.values() if isinstance(n, StartEventNode)]

    @property
    def end_nodes(self) -> List[EndEventNode]:
        return [n for n in self.nodes.values() if isinstance(n, EndEventNode)]

    @property
    def lanes(self) -> List[Lane]:
        """Every lane of every lane set, nested lanes included (depth-first, parents first)."""
        collected: List[Lane] = []

        def visit(lane_set: LaneSet) -> None:
            for lane in lane_set.lanes:
                collected.append(lane)
                if lane.child_lane_set:
                    visit(lane.child_lane_set)

        for lane_set in self.lane_sets:
            visit(lane_set)
        return collected

    def lane_of(self, node_id: str) -> Optional[Lane]:
        """The innermost lane that references the node, if any."""
        found: Optional[Lane] = None
        for lane in self.lanes:
            if node_id in lane.flow_node_refs:
                found = lane
        return found

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
            "participant": self.participant.to_dict() if self.participant else None,
            "lane_sets": [ls.to_dict() for ls in self.lane_sets],
            "start_nodes": [n.id for n in self.start_nodes],
            "end_nodes": [n.id for n in self.end_nodes],
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "edges": {eid: edge.to_dict() for eid, edge in self.edges.items()},
            "documentation": self.documentation,
            "extensions": self.extensions.to_dict(),
        }


@dataclass
class BpmnDocument:
    """A parsed ``<bpmn:definitions>``: every process it contains, none dropped."""

    definitions_id: Optional[str] = None
    name: Optional[str] = None
    target_namespace: Optional[str] = None
    processes: List[ProcessGraph] = field(default_factory=list)
    extensions: Extensions = field(default_factory=Extensions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "definitions_id": self.definitions_id,
            "name": self.name,
            "target_namespace": self.target_namespace,
            "processes": [p.to_dict() for p in self.processes],
            "extensions": self.extensions.to_dict(),
        }
