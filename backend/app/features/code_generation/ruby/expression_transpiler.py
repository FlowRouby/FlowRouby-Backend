"""Translation of FlowSpec expressions to Ruby.

Maps the expression AST (literals, identifiers, unary and binary operators) to Ruby source
text. Identifiers become lookups in the workflow context hash.
"""

from __future__ import annotations

from ...flowspec.ast.nodes import BinaryExprAST, ExprAST, IdentifierAST, LiteralAST, UnaryExprAST


class RubyExpressionTranspiler:
    """Transpiles FlowSpec ExprAST nodes into idiomatic Ruby expressions over @context."""

    def transpile(self, expr: ExprAST, context_var: str = "@context") -> str:
        if isinstance(expr, LiteralAST):
            if expr.literal_type == "boolean":
                return "true" if expr.value else "false"
            if expr.literal_type == "number":
                return str(expr.value)
            escaped = str(expr.value).replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        if isinstance(expr, IdentifierAST):
            if expr.name == "response":
                return "parsed_body"
            return f"{context_var}[:{expr.name}]"

        if isinstance(expr, UnaryExprAST):
            inner = self.transpile(expr.operand, context_var=context_var)
            return f"{expr.operator}({inner})"

        if isinstance(expr, BinaryExprAST):
            left = self.transpile(expr.left, context_var=context_var)
            right = self.transpile(expr.right, context_var=context_var)
            return f"({left} {expr.operator} {right})"

        return "nil"
