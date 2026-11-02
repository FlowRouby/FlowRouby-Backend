"""Translates a BPMN 2.0 XML element tree into the neutral IR.

Namespace handling is URI based (``{uri}tag``), so the XML prefix is irrelevant. Nothing is
dropped silently: elements this module does not interpret are kept as generic content and
reported through diagnostics. Cross-reference and profile checks live in ``validator.py``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from xml.etree.ElementTree import Element

from ..intermediate_model.diagnostics import Diagnostic, DiagnosticCode, Severity
from ..intermediate_model.extensions import ExtensionElement, Extensions
from ..intermediate_model.models import (
    BpmnDocument,
    CallActivityNode,
    Condition,
    EndEventNode,
    FlowNode,
    GatewayNode,
    Lane,
    LaneSet,
    NodeType,
    Participant,
    ProcessGraph,
    ScriptTaskNode,
    SequenceFlowEdge,
    StartEventNode,
    SupportLevel,
    UnsupportedNode,
)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

_TASK_TYPES: Dict[str, NodeType] = {
    "task": NodeType.TASK,
    "userTask": NodeType.USER_TASK,
    "serviceTask": NodeType.SERVICE_TASK,
    "manualTask": NodeType.MANUAL_TASK,
    "sendTask": NodeType.SEND_TASK,
    "receiveTask": NodeType.RECEIVE_TASK,
    "businessRuleTask": NodeType.BUSINESS_RULE_TASK,
}
_GATEWAY_TYPES: Dict[str, NodeType] = {
    "exclusiveGateway": NodeType.EXCLUSIVE_GATEWAY,
    "parallelGateway": NodeType.PARALLEL_GATEWAY,
    "inclusiveGateway": NodeType.INCLUSIVE_GATEWAY,
}
# Flow nodes whose semantics FlowRouby does not model yet.
_UNSUPPORTED_FLOW_NODES = {
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "boundaryEvent",
    "subProcess",
    "adHocSubProcess",
    "transaction",
    "eventBasedGateway",
    "complexGateway",
}
_LOOP_CHARACTERISTICS = {"multiInstanceLoopCharacteristics", "standardLoopCharacteristics"}
# Event definitions that change how control flow ends or diverts, so analysis would misread them.
_BLOCKING_EVENT_DEFINITIONS = {
    "terminateEventDefinition",
    "errorEventDefinition",
    "escalationEventDefinition",
    "cancelEventDefinition",
    "compensateEventDefinition",
}
# Children consumed by every node parser; incoming/outgoing are re-derived from sequence flows.
_COMMON_NODE_CHILDREN = {"documentation", "extensionElements", "incoming", "outgoing"}


def _bpmn(local_name: str) -> str:
    return f"{{{BPMN_NS}}}{local_name}"


def split_tag(tag: str) -> Tuple[Optional[str], str]:
    """Splits ``{uri}local`` into ``(uri, local)``; unqualified tags give ``(None, tag)``."""
    if tag.startswith("{"):
        uri, _, local = tag[1:].partition("}")
        return uri, local
    return None, tag


def to_generic(element: Element) -> ExtensionElement:
    """Copies an XML element (attributes, text and children) into the generic tree."""
    namespace_uri, local_name = split_tag(element.tag)
    text = element.text if element.text and element.text.strip() else None
    return ExtensionElement(
        local_name=local_name,
        namespace_uri=namespace_uri,
        attributes=dict(element.attrib),
        text=text,
        children=[to_generic(child) for child in element],
    )


class _Collector:
    """Accumulates diagnostics and tracks the document-wide id registry."""

    def __init__(self) -> None:
        self.diagnostics: List[Diagnostic] = []
        self._seen_ids: Set[str] = set()

    def add(
        self,
        severity: Severity,
        code: DiagnosticCode,
        message: str,
        element_id: Optional[str] = None,
        element_type: Optional[str] = None,
        process_id: Optional[str] = None,
        blocks_analysis: bool = False,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(severity, code, message, element_id, element_type, process_id, blocks_analysis)
        )

    def register_id(self, element_id: str, element_type: str, process_id: Optional[str]) -> bool:
        """Records an id; reports DUPLICATE_ID and returns False when it was already used."""
        if element_id in self._seen_ids:
            self.add(
                Severity.ERROR,
                DiagnosticCode.DUPLICATE_ID,
                f"The id '{element_id}' is used by more than one element.",
                element_id,
                element_type,
                process_id,
            )
            return False
        self._seen_ids.add(element_id)
        return True

    def require_id(self, element: Element, element_type: str, process_id: Optional[str]) -> Optional[str]:
        """Returns the element id after registering it, or None (with a diagnostic) if unusable."""
        element_id = element.get("id")
        if not element_id:
            self.add(
                Severity.ERROR,
                DiagnosticCode.MISSING_ID,
                f"A <{element_type}> element has no 'id' attribute.",
                None,
                element_type,
                process_id,
            )
            return None
        return element_id if self.register_id(element_id, element_type, process_id) else None

    def keep_unrecognized(
        self, child: Element, parent_id: Optional[str], process_id: Optional[str], sink: List[ExtensionElement]
    ) -> None:
        """Stores an uninterpreted child and reports it according to what it could change."""
        _, local = split_tag(child.tag)
        sink.append(to_generic(child))
        element_id = parent_id
        if local in _LOOP_CHARACTERISTICS or local in _BLOCKING_EVENT_DEFINITIONS:
            self.add(
                Severity.WARNING,
                DiagnosticCode.UNSUPPORTED_ELEMENT,
                f"<{local}> changes how the element behaves and is not interpreted yet; "
                "it is preserved as unrecognized content.",
                element_id,
                local,
                process_id,
                blocks_analysis=True,
            )
        elif local.endswith("EventDefinition"):
            self.add(
                Severity.WARNING,
                DiagnosticCode.UNSUPPORTED_ELEMENT,
                f"<{local}> is preserved as unrecognized content; the event is analyzed as a plain event.",
                element_id,
                local,
                process_id,
            )
        else:
            self.add(
                Severity.INFO,
                DiagnosticCode.IGNORED_ELEMENT,
                f"<{local}> is preserved as unrecognized content and not interpreted.",
                child.get("id") or element_id,
                local,
                process_id,
            )

    def not_imported(self, local: str, element_id: Optional[str], process_id: Optional[str], reason: str) -> None:
        self.add(
            Severity.INFO,
            DiagnosticCode.IGNORED_ELEMENT,
            f"<{local}> is not imported: {reason}",
            element_id,
            local,
            process_id,
        )


def _read_extensions(element: Element) -> Extensions:
    """Foreign-namespace attributes plus the children of every <extensionElements>."""
    attributes = {name: value for name, value in element.attrib.items() if name.startswith("{")}
    elements = [to_generic(child) for ext in element.findall(_bpmn("extensionElements")) for child in ext]
    return Extensions(attributes=attributes, elements=elements)


def _read_documentation(element: Element) -> Optional[str]:
    texts = [d.text for d in element.findall(_bpmn("documentation")) if d.text and d.text.strip()]
    return "\n\n".join(texts) if texts else None


def _parse_node(element: Element, local: str, ctx: _Collector, process_id: str) -> Optional[FlowNode]:
    node_id = ctx.require_id(element, local, process_id)
    if node_id is None:
        return None

    if local in _UNSUPPORTED_FLOW_NODES:
        ctx.add(
            Severity.WARNING,
            DiagnosticCode.UNSUPPORTED_ELEMENT,
            f"<{local}> is not supported yet; it is kept as an opaque node.",
            node_id,
            local,
            process_id,
            blocks_analysis=True,
        )
        return UnsupportedNode(
            id=node_id,
            bpmn_type=local,
            name=element.get("name"),
            documentation=_read_documentation(element),
            default_flow_id=element.get("default"),
            extensions=_read_extensions(element),
            source=to_generic(element),
        )

    common = {
        "id": node_id,
        "name": element.get("name"),
        "documentation": _read_documentation(element),
        "default_flow_id": element.get("default"),
        "extensions": _read_extensions(element),
    }
    handled = set(_COMMON_NODE_CHILDREN)
    node: FlowNode

    if local == "startEvent":
        node = StartEventNode(**common)
    elif local == "endEvent":
        node = EndEventNode(**common)
    elif local in _TASK_TYPES:
        node = FlowNode(node_type=_TASK_TYPES[local], bpmn_type=local, **common)
    elif local == "scriptTask":
        handled.add("script")
        script_element = element.find(_bpmn("script"))
        node = ScriptTaskNode(
            script_format=element.get("scriptFormat"),
            script=script_element.text if script_element is not None else None,
            **common,
        )
    elif local == "callActivity":
        node = CallActivityNode(called_element=element.get("calledElement"), **common)
        node.support = SupportLevel.PRESERVED
        ctx.add(
            Severity.WARNING,
            DiagnosticCode.PRESERVED_NOT_ANALYZABLE,
            "Call activities are preserved, but the called process is not followed; "
            "formal analysis treats the activity as a single atomic step.",
            node_id,
            local,
            process_id,
        )
    elif local in _GATEWAY_TYPES:
        node = GatewayNode(node_type=_GATEWAY_TYPES[local], bpmn_type=local, **common)
        if local == "inclusiveGateway":
            node.support = SupportLevel.PRESERVED
            ctx.add(
                Severity.WARNING,
                DiagnosticCode.PRESERVED_NOT_ANALYZABLE,
                "Inclusive gateways are preserved, but their analysis is experimental.",
                node_id,
                local,
                process_id,
            )
    else:  # pragma: no cover - callers only pass tags handled above
        raise ValueError(f"Unexpected flow node tag '{local}'")

    for child in element:
        child_ns, child_local = split_tag(child.tag)
        if child_ns == BPMN_NS and child_local in handled:
            continue
        ctx.keep_unrecognized(child, node_id, process_id, node.unrecognized)
        if child_local in _LOOP_CHARACTERISTICS or child_local in _BLOCKING_EVENT_DEFINITIONS:
            node.support = SupportLevel.PRESERVED
    return node


def _parse_sequence_flow(element: Element, ctx: _Collector, process_id: str) -> Optional[SequenceFlowEdge]:
    flow_id = ctx.require_id(element, "sequenceFlow", process_id)
    if flow_id is None:
        return None
    source_ref = element.get("sourceRef")
    target_ref = element.get("targetRef")
    for attr, value in (("sourceRef", source_ref), ("targetRef", target_ref)):
        if not value:
            ctx.add(
                Severity.ERROR,
                DiagnosticCode.MISSING_REF_ATTRIBUTE,
                f"The sequenceFlow '{flow_id}' has no '{attr}' attribute.",
                flow_id,
                "sequenceFlow",
                process_id,
            )
    if not source_ref or not target_ref:
        return None

    edge = SequenceFlowEdge(
        id=flow_id,
        source_ref=source_ref,
        target_ref=target_ref,
        name=element.get("name"),
        documentation=_read_documentation(element),
        extensions=_read_extensions(element),
    )
    handled = {"documentation", "extensionElements", "conditionExpression"}
    condition = element.find(_bpmn("conditionExpression"))
    if condition is not None:
        edge.condition = Condition(
            text=condition.text or "",
            language=condition.get("language"),
            xsi_type=condition.get(f"{{{XSI_NS}}}type"),
        )
    for child in element:
        child_ns, child_local = split_tag(child.tag)
        if child_ns == BPMN_NS and child_local in handled:
            continue
        ctx.keep_unrecognized(child, flow_id, process_id, edge.unrecognized)
    return edge


def _parse_lane_set(element: Element, ctx: _Collector, process_id: str) -> LaneSet:
    lane_set = LaneSet(id=element.get("id"), name=element.get("name"))
    if lane_set.id:
        ctx.register_id(lane_set.id, "laneSet", process_id)
    for child in element:
        child_ns, child_local = split_tag(child.tag)
        if child_ns == BPMN_NS and child_local == "lane":
            lane = _parse_lane(child, ctx, process_id)
            if lane is not None:
                lane_set.lanes.append(lane)
        else:
            ctx.not_imported(child_local, child.get("id"), process_id, "only lanes are read from a laneSet.")
    return lane_set


def _parse_lane(element: Element, ctx: _Collector, process_id: str) -> Optional[Lane]:
    lane_id = ctx.require_id(element, "lane", process_id)
    if lane_id is None:
        return None
    lane = Lane(id=lane_id, name=element.get("name"))
    for child in element:
        child_ns, child_local = split_tag(child.tag)
        if child_ns == BPMN_NS and child_local == "flowNodeRef":
            if child.text and child.text.strip():
                lane.flow_node_refs.append(child.text.strip())
        elif child_ns == BPMN_NS and child_local == "childLaneSet":
            lane.child_lane_set = _parse_lane_set(child, ctx, process_id)
        else:
            ctx.not_imported(child_local, child.get("id"), process_id, "only lane membership is read.")
    return lane


def _link_flows(graph: ProcessGraph) -> None:
    """Derives incoming/outgoing flow ids and default-flow markers. Dangling refs are skipped
    here and reported by the validator."""
    for edge in graph.edges.values():
        source = graph.nodes.get(edge.source_ref)
        target = graph.nodes.get(edge.target_ref)
        if source is not None:
            source.outgoing_flows.append(edge.id)
            if source.default_flow_id == edge.id:
                edge.is_default = True
        if target is not None:
            target.incoming_flows.append(edge.id)


def _parse_process(element: Element, ctx: _Collector) -> Optional[ProcessGraph]:
    process_id = ctx.require_id(element, "process", None)
    if process_id is None:
        return None
    is_executable_attr = element.get("isExecutable")
    graph = ProcessGraph(
        process_id=process_id,
        name=element.get("name"),
        is_executable=None if is_executable_attr is None else is_executable_attr.strip().lower() == "true",
        documentation=_read_documentation(element),
        extensions=_read_extensions(element),
    )
    handled = {"documentation", "extensionElements"}
    for child in element:
        child_ns, local = split_tag(child.tag)
        if child_ns != BPMN_NS or local in handled:
            if child_ns != BPMN_NS:
                ctx.keep_unrecognized(child, process_id, process_id, graph.unrecognized)
            continue
        if local == "laneSet":
            graph.lane_sets.append(_parse_lane_set(child, ctx, process_id))
        elif local == "sequenceFlow":
            edge = _parse_sequence_flow(child, ctx, process_id)
            if edge is not None:
                graph.edges[edge.id] = edge
        elif local in _TASK_TYPES or local in _GATEWAY_TYPES or local in _UNSUPPORTED_FLOW_NODES or local in (
            "startEvent",
            "endEvent",
            "scriptTask",
            "callActivity",
        ):
            node = _parse_node(child, local, ctx, process_id)
            if node is not None:
                graph.nodes[node.id] = node
        else:
            ctx.keep_unrecognized(child, process_id, process_id, graph.unrecognized)
    _link_flows(graph)
    return graph


def _parse_collaboration(element: Element, document: BpmnDocument, ctx: _Collector) -> None:
    collaboration_id = element.get("id")
    if collaboration_id:
        ctx.register_id(collaboration_id, "collaboration", None)
    for child in element:
        child_ns, local = split_tag(child.tag)
        if child_ns == BPMN_NS and local == "participant":
            participant_id = ctx.require_id(child, "participant", None)
            if participant_id is not None:
                document.participants.append(
                    Participant(id=participant_id, name=child.get("name"), process_ref=child.get("processRef"))
                )
        else:
            ctx.keep_unrecognized(child, collaboration_id, None, document.unrecognized)


def parse_document(root: Element) -> Tuple[Optional[BpmnDocument], List[Diagnostic]]:
    """Builds the IR from a parsed XML root. Returns ``(None, diagnostics)`` if it is not BPMN."""
    ctx = _Collector()
    if root.tag != _bpmn("definitions"):
        ctx.add(
            Severity.ERROR,
            DiagnosticCode.NOT_BPMN,
            f"The root element must be <definitions> in the BPMN 2.0 model namespace ({BPMN_NS}); "
            f"found '{root.tag}'.",
            element_type=split_tag(root.tag)[1],
        )
        return None, ctx.diagnostics

    document = BpmnDocument(
        definitions_id=root.get("id"),
        name=root.get("name"),
        target_namespace=root.get("targetNamespace"),
        extensions=_read_extensions(root),
    )
    if document.definitions_id:
        ctx.register_id(document.definitions_id, "definitions", None)

    handled = {"extensionElements"}
    for child in root:
        child_ns, local = split_tag(child.tag)
        if child_ns == BPMN_NS and local == "process":
            process = _parse_process(child, ctx)
            if process is not None:
                document.processes.append(process)
        elif child_ns == BPMN_NS and local == "collaboration":
            _parse_collaboration(child, document, ctx)
        elif child_ns == BPMNDI_NS:
            ctx.not_imported(
                local,
                child.get("id"),
                None,
                "diagram layout is not part of the IR; keep the original XML to preserve it.",
            )
        elif child_ns == BPMN_NS and local in handled:
            continue
        else:
            ctx.keep_unrecognized(child, root.get("id"), None, document.unrecognized)

    for process in document.processes:
        for participant in document.participants:
            if participant.process_ref == process.process_id:
                process.participant = participant
    return document, ctx.diagnostics
