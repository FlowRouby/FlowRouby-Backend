"""Structural and profile checks over an already built IR.

Two kinds of rules live here and are labeled as such in every message:

* BPMN reference integrity (a flow must connect existing elements, and so on), and
* FlowRouby profile rules, which are choices of this project and not universal BPMN
  requirements (for example, a process must have a start and an end event to be imported).
"""

from __future__ import annotations

from typing import List

from ..intermediate_model.diagnostics import Diagnostic, DiagnosticCode, Severity
from ..intermediate_model.models import (
    BpmnDocument,
    EndEventNode,
    GatewayNode,
    NodeType,
    ProcessGraph,
    StartEventNode,
    UnsupportedNode,
)


def validate_document(document: BpmnDocument) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    process_ids = {p.process_id for p in document.processes}

    if not document.processes:
        diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                DiagnosticCode.NO_PROCESS,
                "The document contains no <process> element.",
                element_type="process",
            )
        )
    elif len(document.processes) > 1:
        diagnostics.append(
            Diagnostic(
                Severity.WARNING,
                DiagnosticCode.MULTIPLE_PROCESSES,
                f"The document contains {len(document.processes)} processes "
                f"({', '.join(sorted(process_ids))}). All are imported, but FlowRouby profile analysis "
                "works on one process at a time.",
                element_type="process",
                blocks_analysis=True,
            )
        )

    for participant in document.participants:
        if participant.process_ref and participant.process_ref not in process_ids:
            diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    DiagnosticCode.INVALID_REFERENCE,
                    f"The participant '{participant.id}' references the unknown process "
                    f"'{participant.process_ref}'.",
                    participant.id,
                    "participant",
                )
            )

    for process in document.processes:
        diagnostics.extend(_check_references(process))
        diagnostics.extend(_check_profile_rules(process))
        diagnostics.extend(_check_structure(process))
    return diagnostics


def _error_ref(process: ProcessGraph, element_id: str, element_type: str, message: str) -> Diagnostic:
    return Diagnostic(
        Severity.ERROR, DiagnosticCode.INVALID_REFERENCE, message, element_id, element_type, process.process_id
    )


def _check_references(process: ProcessGraph) -> List[Diagnostic]:
    found: List[Diagnostic] = []
    for edge in process.edges.values():
        if edge.source_ref not in process.nodes:
            found.append(
                _error_ref(
                    process,
                    edge.id,
                    "sequenceFlow",
                    f"The sequenceFlow '{edge.id}' references the unknown sourceRef '{edge.source_ref}'.",
                )
            )
        if edge.target_ref not in process.nodes:
            found.append(
                _error_ref(
                    process,
                    edge.id,
                    "sequenceFlow",
                    f"The sequenceFlow '{edge.id}' references the unknown targetRef '{edge.target_ref}'.",
                )
            )
    for lane in process.lanes:
        for ref in lane.flow_node_refs:
            if ref not in process.nodes:
                found.append(
                    _error_ref(
                        process, lane.id, "lane", f"The lane '{lane.id}' references the unknown flow node '{ref}'."
                    )
                )
    for node in process.nodes.values():
        if node.default_flow_id is None:
            continue
        default_edge = process.edges.get(node.default_flow_id)
        if default_edge is None or default_edge.source_ref != node.id:
            found.append(
                _error_ref(
                    process,
                    node.id,
                    node.bpmn_type,
                    f"The default flow '{node.default_flow_id}' of '{node.id}' is not one of its outgoing "
                    "sequence flows.",
                )
            )
    return found


def _check_profile_rules(process: ProcessGraph) -> List[Diagnostic]:
    found: List[Diagnostic] = []
    pid = process.process_id
    starts = process.start_nodes
    if not starts:
        found.append(
            Diagnostic(
                Severity.ERROR,
                DiagnosticCode.NO_START_EVENT,
                f"FlowRouby import profile: process '{pid}' must contain a startEvent. "
                "This is a FlowRouby restriction, not a general BPMN rule.",
                element_type="startEvent",
                process_id=pid,
            )
        )
    elif len(starts) > 1:
        found.append(
            Diagnostic(
                Severity.WARNING,
                DiagnosticCode.MULTIPLE_START_EVENTS,
                f"FlowRouby analysis profile: process '{pid}' has {len(starts)} start events "
                f"({', '.join(n.id for n in starts)}). It is imported, but analysis is blocked until "
                "multiple start events have a formal representation.",
                element_type="startEvent",
                process_id=pid,
                blocks_analysis=True,
            )
        )
    if not process.end_nodes:
        found.append(
            Diagnostic(
                Severity.ERROR,
                DiagnosticCode.NO_END_EVENT,
                f"FlowRouby import profile: process '{pid}' must contain an endEvent. "
                "This is a FlowRouby restriction, not a general BPMN rule.",
                element_type="endEvent",
                process_id=pid,
            )
        )
    return found


def _check_structure(process: ProcessGraph) -> List[Diagnostic]:
    found: List[Diagnostic] = []
    pid = process.process_id
    for node in process.nodes.values():
        if isinstance(node, UnsupportedNode):
            continue
        no_in, no_out = not node.incoming_flows, not node.outgoing_flows
        disconnected = (
            (no_in and no_out)
            or (isinstance(node, StartEventNode) and no_out)
            or (isinstance(node, EndEventNode) and no_in)
        )
        if disconnected:
            found.append(
                Diagnostic(
                    Severity.WARNING,
                    DiagnosticCode.DISCONNECTED_NODE,
                    f"The {node.bpmn_type} '{node.id}' is not connected to the rest of the process flow.",
                    node.id,
                    node.bpmn_type,
                    pid,
                )
            )
        if isinstance(node, GatewayNode) and no_out:
            found.append(
                Diagnostic(
                    Severity.WARNING,
                    DiagnosticCode.GATEWAY_WITHOUT_OUTGOING,
                    f"The {node.bpmn_type} '{node.id}' has no outgoing sequence flow.",
                    node.id,
                    node.bpmn_type,
                    pid,
                )
            )
        if node.node_type is NodeType.EXCLUSIVE_GATEWAY and len(node.outgoing_flows) > 1:
            for edge in process.get_outgoing_edges(node.id):
                if edge.condition is None and not edge.is_default:
                    found.append(
                        Diagnostic(
                            Severity.WARNING,
                            DiagnosticCode.XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT,
                            f"The sequenceFlow '{edge.id}' leaves the exclusive gateway '{node.id}' without "
                            "a condition and is not its default flow.",
                            edge.id,
                            "sequenceFlow",
                            pid,
                        )
                    )
    return found
