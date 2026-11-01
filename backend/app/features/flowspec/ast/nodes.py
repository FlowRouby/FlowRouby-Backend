"""Abstract Syntax Tree (AST) node definitions for the FlowSpec intermediate DSL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# ============================================================================
# Expression AST Nodes (Chomsky Type 2 recursive expressions)
# ============================================================================

@dataclass
class ExprAST:
    """Base class for FlowSpec expressions."""
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError


@dataclass
class LiteralAST(ExprAST):
    value: Union[int, float, str, bool] = ""
    literal_type: str = "string"  # "number", "string", "boolean"

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "Literal", "type": self.literal_type, "value": self.value}


@dataclass
class IdentifierAST(ExprAST):
    name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "Identifier", "name": self.name}


@dataclass
class UnaryExprAST(ExprAST):
    operator: str = "!"
    operand: ExprAST = field(default_factory=ExprAST)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "UnaryExpr",
            "operator": self.operator,
            "operand": self.operand.to_dict(),
        }


@dataclass
class BinaryExprAST(ExprAST):
    operator: str = "=="
    left: ExprAST = field(default_factory=ExprAST)
    right: ExprAST = field(default_factory=ExprAST)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "BinaryExpr",
            "operator": self.operator,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


# ============================================================================
# Task Attribute & Statement AST Nodes
# ============================================================================

@dataclass
class FormFieldAST:
    name: str
    field_type: str  # boolean, long, integer, string
    label: str = ""
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "type": self.field_type, "label": self.label}


@dataclass
class HttpConnectorAST:
    method: str = "GET"
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    payload_fields: Dict[str, ExprAST] = field(default_factory=dict)
    output_target: Optional[str] = None
    output_source: Optional[str] = None
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "headers": dict(self.headers),
            "payload_fields": {k: v.to_dict() for k, v in self.payload_fields.items()},
            "output_target": self.output_target,
            "output_source": self.output_source,
        }


@dataclass
class IOMappingAST:
    direction: str  # "input" or "output"
    target: str
    expr: ExprAST
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "target": self.target,
            "expr": self.expr.to_dict(),
        }


@dataclass
class GatewayBranchAST:
    branch_kind: str  # "when", "default", "branch"
    target_id: str
    condition: Optional[ExprAST] = None
    label: str = ""
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch_kind": self.branch_kind,
            "target_id": self.target_id,
            "condition": self.condition.to_dict() if self.condition else None,
            "label": self.label,
        }


# ============================================================================
# Flow Node AST Declarations
# ============================================================================

@dataclass
class NodeAST:
    id: str
    name: str
    kind: str  # "start", "end", "user_task", "service_task", "script_task", "manual_task", "business_rule_task", "call_activity", "exclusive_gateway", "parallel_gateway", "inclusive_gateway"
    lane: Optional[str] = None
    transitions: List[str] = field(default_factory=list)
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "lane": self.lane,
            "transitions": list(self.transitions),
        }


@dataclass
class TaskNodeAST(NodeAST):
    form_ref: Optional[str] = None
    form_fields: List[FormFieldAST] = field(default_factory=list)
    delegate_class: Optional[str] = None
    http_connector: Optional[HttpConnectorAST] = None
    decision_ref: Optional[str] = None
    result_variable: Optional[str] = None
    called_element: Optional[str] = None
    script: Optional[str] = None
    io_mappings: List[IOMappingAST] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "form_ref": self.form_ref,
                "form_fields": [f.to_dict() for f in self.form_fields],
                "delegate_class": self.delegate_class,
                "http_connector": self.http_connector.to_dict() if self.http_connector else None,
                "decision_ref": self.decision_ref,
                "result_variable": self.result_variable,
                "called_element": self.called_element,
                "script": self.script,
                "io_mappings": [m.to_dict() for m in self.io_mappings],
            }
        )
        return base


@dataclass
class GatewayAST(NodeAST):
    branches: List[GatewayBranchAST] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["branches"] = [b.to_dict() for b in self.branches]
        return base


@dataclass
class LaneAST:
    name: str
    nodes: List[NodeAST] = field(default_factory=list)
    line: int = 0
    column: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
        }


@dataclass
class ProcessAST:
    process_id: str
    name: str
    lanes: List[LaneAST] = field(default_factory=list)
    nodes: List[NodeAST] = field(default_factory=list)
    line: int = 0
    column: int = 0

    @property
    def all_nodes(self) -> List[NodeAST]:
        result: List[NodeAST] = list(self.nodes)
        for lane in self.lanes:
            result.extend(lane.nodes)
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "process_id": self.process_id,
            "name": self.name,
            "lanes": [l.to_dict() for l in self.lanes],
            "unassigned_nodes": [n.to_dict() for n in self.nodes],
        }

