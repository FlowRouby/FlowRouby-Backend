"""Sequential role-based node ID normalization for ProcessGraph."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Dict, List, Set, Tuple

from .models import NodeType, ProcessGraph

_ROLE_PREFIXES: Dict[NodeType, str] = {
    NodeType.START_EVENT: "start",
    NodeType.END_EVENT: "end",
    NodeType.EXCLUSIVE_GATEWAY: "decision",
    NodeType.PARALLEL_GATEWAY: "parallel",
    NodeType.INCLUSIVE_GATEWAY: "inclusive",
    NodeType.TASK: "task",
    NodeType.USER_TASK: "task",
    NodeType.SERVICE_TASK: "task",
    NodeType.SCRIPT_TASK: "task",
    NodeType.MANUAL_TASK: "task",
    NodeType.SEND_TASK: "task",
    NodeType.RECEIVE_TASK: "task",
    NodeType.BUSINESS_RULE_TASK: "task",
    NodeType.CALL_ACTIVITY: "task",
    NodeType.UNSUPPORTED: "node",
}


def symbolize_node_ids(graph: ProcessGraph) -> Tuple[ProcessGraph, Dict[str, str]]:
    """Returns a copy of the graph whose nodes use sequential symbols, plus the symbol -> BPMN id map.

    The imported graph is left untouched, so original BPMN ids are never lost.
    """
    symbolic_graph = deepcopy(graph)
    id_map = normalize_node_ids(symbolic_graph)
    return symbolic_graph, {symbol: bpmn_id for bpmn_id, symbol in id_map.items()}


def normalize_node_ids(graph: ProcessGraph) -> Dict[str, str]:
    """Rewrites node IDs in place, in BFS order, using sequential role-based names (e.g. start_1, task_1, decision_1, end_1).

    Returns the BPMN id -> symbol map. Prefer ``symbolize_node_ids`` to keep the original graph.
    """
    ordered_ids: List[str] = []
    visited: Set[str] = set()
    queue: deque[str] = deque(n.id for n in graph.start_nodes)

    while queue:
        curr = queue.popleft()
        if curr in visited or curr not in graph.nodes:
            continue
        visited.add(curr)
        ordered_ids.append(curr)
        for edge in graph.get_outgoing_edges(curr):
            if edge.target_ref not in visited:
                queue.append(edge.target_ref)

    for node_id in graph.nodes:
        if node_id not in visited:
            visited.add(node_id)
            ordered_ids.append(node_id)

    counters: Dict[str, int] = {}
    id_map: Dict[str, str] = {}
    for old_id in ordered_ids:
        node = graph.nodes[old_id]
        prefix = _ROLE_PREFIXES.get(node.node_type, "node")
        counters[prefix] = counters.get(prefix, 0) + 1
        id_map[old_id] = f"{prefix}_{counters[prefix]}"

    new_nodes = {}
    for old_id in ordered_ids:
        node = graph.nodes[old_id]
        new_id = id_map[old_id]
        node.id = new_id
        new_nodes[new_id] = node
    graph.nodes = new_nodes

    for edge in graph.edges.values():
        edge.source_ref = id_map.get(edge.source_ref, edge.source_ref)
        edge.target_ref = id_map.get(edge.target_ref, edge.target_ref)

    for lane in graph.lanes:
        lane.flow_node_refs = [id_map.get(ref, ref) for ref in lane.flow_node_refs]

    return id_map
