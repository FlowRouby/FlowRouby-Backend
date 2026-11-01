"""Semantic Analyzer and Symbol Table for FlowSpec AST, plus Stateless Dry-Run Simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ..ast.nodes import (
    BinaryExprAST,
    ExprAST,
    GatewayAST,
    IdentifierAST,
    LiteralAST,
    NodeAST,
    ProcessAST,
    TaskNodeAST,
    UnaryExprAST,
)


@dataclass
class VariableSymbol:
    name: str
    inferred_type: str  # "boolean", "number", "string", "any"
    origin_kind: str    # "form_field", "external_input", "http_output", "decision_output", "computed_output"
    defined_in: List[str] = field(default_factory=list)
    used_in: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "inferred_type": self.inferred_type,
            "origin_kind": self.origin_kind,
            "defined_in": list(self.defined_in),
            "used_in": list(self.used_in),
        }


@dataclass
class SemanticAnalysisResult:
    valid: bool
    node_symbols: Dict[str, NodeAST]
    variable_symbols: Dict[str, VariableSymbol]
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    data_contract: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "symbol_table": {
                "nodes_count": len(self.node_symbols),
                "variables": {k: v.to_dict() for k, v in self.variable_symbols.items()},
            },
        }


class FlowSpecSemanticAnalyzer:
    """Performs context-sensitive checks (Symbol Table, Node Reference Resolution, and Type Checking)."""

    TYPE_MAP = {
        "boolean": "boolean",
        "bool": "boolean",
        "long": "number",
        "integer": "number",
        "int": "number",
        "double": "number",
        "number": "number",
        "string": "string",
        "enum": "string",
        "date": "string",
    }

    def analyze(self, ast: ProcessAST) -> SemanticAnalysisResult:
        node_symbols: Dict[str, NodeAST] = {}
        variable_symbols: Dict[str, VariableSymbol] = {}
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        # Pass 1: Register all nodes and declared variables in Symbol Table
        for node in ast.all_nodes:
            if node.id in node_symbols:
                errors.append(
                    {
                        "type": "DUPLICATE_NODE_ID",
                        "node_id": node.id,
                        "line": node.line,
                        "message": f"Duplicate node identifier '{node.id}'.",
                    }
                )
            node_symbols[node.id] = node

            if isinstance(node, TaskNodeAST):
                for ff in node.form_fields:
                    norm_type = self.TYPE_MAP.get(ff.field_type.lower(), "string")
                    self._register_variable(
                        variable_symbols, ff.name, norm_type, "form_field", defined_in=node.id
                    )

                if node.decision_ref and node.result_variable:
                    self._register_variable(
                        variable_symbols,
                        node.result_variable,
                        "number",
                        "decision_output",
                        defined_in=node.id,
                    )

                if node.http_connector and node.http_connector.output_target:
                    self._register_variable(
                        variable_symbols,
                        node.http_connector.output_target,
                        "any",
                        "http_output",
                        defined_in=node.id,
                    )

        # Pass 2: Validate transitions, IO expressions, HTTP payloads, and Gateway conditions
        for node in ast.all_nodes:
            for target_id in node.transitions:
                if target_id not in node_symbols:
                    errors.append(
                        {
                            "type": "UNDECLARED_NODE_REFERENCE",
                            "node_id": node.id,
                            "target_id": target_id,
                            "line": node.line,
                            "message": f"Node '{node.id}' transitions to undeclared node '{target_id}'.",
                        }
                    )

            if isinstance(node, TaskNodeAST):
                if node.http_connector:
                    for key, expr in node.http_connector.payload_fields.items():
                        self._check_expr_type(expr, node.id, variable_symbols, errors, expected_hint="any")

                for mapping in node.io_mappings:
                    inferred = self._check_expr_type(
                        mapping.expr, node.id, variable_symbols, errors, expected_hint="any"
                    )
                    if mapping.direction == "output":
                        self._register_variable(
                            variable_symbols,
                            mapping.target,
                            inferred,
                            "computed_output",
                            defined_in=node.id,
                        )

            elif isinstance(node, GatewayAST):
                default_count = sum(1 for b in node.branches if b.branch_kind == "default")
                if default_count > 1:
                    errors.append(
                        {
                            "type": "MULTIPLE_DEFAULT_BRANCHES",
                            "node_id": node.id,
                            "line": node.line,
                            "message": f"Gateway '{node.id}' defines more than one default branch.",
                        }
                    )
                for branch in node.branches:
                    if branch.condition is not None:
                        cond_type = self._check_expr_type(
                            branch.condition,
                            node.id,
                            variable_symbols,
                            errors,
                            expected_hint="boolean",
                        )
                        if cond_type not in ("boolean", "any"):
                            errors.append(
                                {
                                    "type": "TYPE_MISMATCH",
                                    "node_id": node.id,
                                    "line": branch.line,
                                    "message": (
                                        f"Condition in gateway '{node.id}' must evaluate to boolean, "
                                        f"got '{cond_type}'."
                                    ),
                                }
                            )

        data_contract = self._build_data_contract(variable_symbols)
        return SemanticAnalysisResult(
            valid=(len(errors) == 0),
            node_symbols=node_symbols,
            variable_symbols=variable_symbols,
            errors=errors,
            warnings=warnings,
            data_contract=data_contract,
        )

    def _register_variable(
        self,
        table: Dict[str, VariableSymbol],
        name: str,
        inferred_type: str,
        origin_kind: str,
        defined_in: Optional[str] = None,
        used_in: Optional[str] = None,
    ) -> VariableSymbol:
        if name not in table:
            table[name] = VariableSymbol(
                name=name,
                inferred_type=inferred_type,
                origin_kind=origin_kind,
            )
        sym = table[name]
        if sym.inferred_type == "any" and inferred_type != "any":
            sym.inferred_type = inferred_type
        if defined_in and defined_in not in sym.defined_in:
            sym.defined_in.append(defined_in)
        if used_in and used_in not in sym.used_in:
            sym.used_in.append(used_in)
        return sym

    def _check_expr_type(
        self,
        expr: ExprAST,
        node_id: str,
        table: Dict[str, VariableSymbol],
        errors: List[Dict[str, Any]],
        expected_hint: str = "any",
    ) -> str:
        if isinstance(expr, LiteralAST):
            return expr.literal_type

        if isinstance(expr, IdentifierAST):
            if expr.name == "response":
                return "any"
            sym = self._register_variable(
                table,
                expr.name,
                expected_hint if expected_hint != "boolean" else "any",
                "external_input",
                used_in=node_id,
            )
            return sym.inferred_type

        if isinstance(expr, UnaryExprAST):
            sub_type = self._check_expr_type(expr.operand, node_id, table, errors)
            if expr.operator == "!":
                if sub_type not in ("boolean", "any"):
                    errors.append(
                        {
                            "type": "TYPE_MISMATCH",
                            "node_id": node_id,
                            "line": expr.line,
                            "message": f"Logical negation '!' requires boolean operand, got '{sub_type}'.",
                        }
                    )
                return "boolean"
            if expr.operator == "-":
                if sub_type not in ("number", "any"):
                    errors.append(
                        {
                            "type": "TYPE_MISMATCH",
                            "node_id": node_id,
                            "line": expr.line,
                            "message": f"Unary '-' requires numeric operand, got '{sub_type}'.",
                        }
                    )
                return "number"

        if isinstance(expr, BinaryExprAST):
            op = expr.operator
            if op in ("+", "-", "*", "/"):
                lt = self._check_expr_type(expr.left, node_id, table, errors, expected_hint="number")
                rt = self._check_expr_type(expr.right, node_id, table, errors, expected_hint="number")
                if lt not in ("number", "any") or rt not in ("number", "any"):
                    errors.append(
                        {
                            "type": "TYPE_MISMATCH",
                            "node_id": node_id,
                            "line": expr.line,
                            "message": f"Arithmetic operator '{op}' requires numeric operands, got '{lt}' and '{rt}'.",
                        }
                    )
                return "number"

            if op in ("<", "<=", ">", ">="):
                lt = self._check_expr_type(expr.left, node_id, table, errors, expected_hint="number")
                rt = self._check_expr_type(expr.right, node_id, table, errors, expected_hint="number")
                if lt not in ("number", "any") or rt not in ("number", "any"):
                    errors.append(
                        {
                            "type": "TYPE_MISMATCH",
                            "node_id": node_id,
                            "line": expr.line,
                            "message": f"Relational operator '{op}' requires numeric operands, got '{lt}' and '{rt}'.",
                        }
                    )
                return "boolean"

            if op in ("==", "!="):
                lt = self._check_expr_type(expr.left, node_id, table, errors)
                rt = self._check_expr_type(expr.right, node_id, table, errors)
                # Update identifier type if compared against a typed literal
                if isinstance(expr.left, IdentifierAST) and rt in ("boolean", "number", "string"):
                    sym = table.get(expr.left.name)
                    if sym and sym.inferred_type == "any":
                        sym.inferred_type = rt
                        lt = rt
                if isinstance(expr.right, IdentifierAST) and lt in ("boolean", "number", "string"):
                    sym = table.get(expr.right.name)
                    if sym and sym.inferred_type == "any":
                        sym.inferred_type = lt
                        rt = lt
                if lt != "any" and rt != "any" and lt != rt:
                    errors.append(
                        {
                            "type": "TYPE_MISMATCH",
                            "node_id": node_id,
                            "line": expr.line,
                            "message": f"Cannot compare incompatible types '{lt}' and '{rt}' with '{op}'.",
                        }
                    )
                return "boolean"

            if op in ("&&", "||"):
                lt = self._check_expr_type(expr.left, node_id, table, errors, expected_hint="boolean")
                rt = self._check_expr_type(expr.right, node_id, table, errors, expected_hint="boolean")
                if lt not in ("boolean", "any") or rt not in ("boolean", "any"):
                    errors.append(
                        {
                            "type": "TYPE_MISMATCH",
                            "node_id": node_id,
                            "line": expr.line,
                            "message": f"Logical operator '{op}' requires boolean operands, got '{lt}' and '{rt}'.",
                        }
                    )
                return "boolean"

        return "any"

    def _build_data_contract(self, table: Dict[str, VariableSymbol]) -> Dict[str, Any]:
        required_inputs: List[Dict[str, Any]] = []
        produced_outputs: List[Dict[str, Any]] = []
        sample_payload: Dict[str, Any] = {}

        for sym in table.values():
            if sym.origin_kind in ("form_field", "external_input") or not sym.defined_in:
                required_inputs.append(
                    {
                        "name": sym.name,
                        "type": sym.inferred_type if sym.inferred_type != "any" else "string",
                        "origin": sym.origin_kind,
                        "used_in": sym.used_in,
                    }
                )
                sample_payload[sym.name] = self._sample_value_for(sym.name, sym.inferred_type)
            else:
                produced_outputs.append(
                    {
                        "name": sym.name,
                        "type": sym.inferred_type if sym.inferred_type != "any" else "string",
                        "origin": sym.origin_kind,
                        "defined_in": sym.defined_in,
                    }
                )
                # Also provide mock override in sample_payload if used in conditions
                if sym.used_in:
                    sample_payload[sym.name] = self._sample_value_for(sym.name, sym.inferred_type)

        return {
            "required_inputs": required_inputs,
            "produced_outputs": produced_outputs,
            "sample_payload": sample_payload,
        }

    @staticmethod
    def _sample_value_for(name: str, var_type: str) -> Any:
        if var_type == "boolean":
            return True
        if var_type == "number":
            return 100
        return f"sample_{name}"

