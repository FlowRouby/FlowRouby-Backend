"""Vanilla Python LL(1) Recursive Descent Parser for the FlowSpec Context-Free Grammar (Chomsky Type 2)."""

from __future__ import annotations

from typing import Dict, List, Optional

from ..ast.nodes import (
    BinaryExprAST,
    ExprAST,
    FormFieldAST,
    GatewayAST,
    GatewayBranchAST,
    HttpConnectorAST,
    IdentifierAST,
    IOMappingAST,
    LaneAST,
    LiteralAST,
    NodeAST,
    ProcessAST,
    TaskNodeAST,
    UnaryExprAST,
)
from ..lexer.lexer import FlowSpecLexer, Token, TokenType


class FlowSpecSyntaxError(Exception):
    """Raised when the FlowSpec parser encounters a syntax error in the token stream."""

    def __init__(self, message: str, line: int, column: int, token_value: str = ""):
        super().__init__(f"[Line {line}, Col {column}] SyntaxError: {message}")
        self.message = message
        self.line = line
        self.column = column
        self.token_value = token_value


TASK_TOKEN_TYPES = {
    TokenType.USER_TASK,
    TokenType.SERVICE_TASK,
    TokenType.SCRIPT_TASK,
    TokenType.MANUAL_TASK,
    TokenType.BUSINESS_RULE_TASK,
    TokenType.CALL_ACTIVITY,
}

GATEWAY_TOKEN_TYPES = {
    TokenType.EXCLUSIVE_GATEWAY,
    TokenType.PARALLEL_GATEWAY,
    TokenType.INCLUSIVE_GATEWAY,
}

IDENTIFIER_LIKE_TOKENS = {
    TokenType.IDENTIFIER,
    TokenType.METHOD,
    TokenType.URL,
    TokenType.HEADERS,
    TokenType.PAYLOAD,
    TokenType.INPUT,
    TokenType.OUTPUT,
    TokenType.SCRIPT,
}


class FlowSpecParser:
    """LL(1) Recursive Descent Parser that builds a ProcessAST from FlowSpec DSL code."""

    def __init__(self) -> None:
        self.lexer = FlowSpecLexer()
        self.tokens: List[Token] = []
        self.pos: int = 0

    def parse(self, source_code: str) -> ProcessAST:
        self.tokens = self.lexer.tokenize(source_code)
        self.pos = 0
        process_ast = self._parse_program()
        self._expect(TokenType.EOF)
        return process_ast

    def parse_expression_string(self, expr_source: str) -> ExprAST:
        """Parses a standalone expression string into an ExprAST."""
        self.tokens = self.lexer.tokenize(expr_source)
        self.pos = 0
        expr = self._parse_expr()
        self._expect(TokenType.EOF)
        return expr

    # ========================================================================
    # Token stream helpers
    # ========================================================================

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def _match(self, *types: TokenType) -> Optional[Token]:
        if self._current().type in types:
            return self._advance()
        return None

    def _expect(self, expected_type: TokenType, custom_msg: Optional[str] = None) -> Token:
        tok = self._current()
        if tok.type != expected_type:
            msg = custom_msg or f"Expected {expected_type.value}, but got {tok.type.value} ('{tok.value}')"
            raise FlowSpecSyntaxError(msg, tok.line, tok.column, tok.value)
        return self._advance()

    def _expect_identifier_name(self) -> Token:
        tok = self._current()
        if tok.type in IDENTIFIER_LIKE_TOKENS:
            return self._advance()
        raise FlowSpecSyntaxError(
            f"Expected identifier, got {tok.type.value} ('{tok.value}')",
            tok.line,
            tok.column,
            tok.value,
        )

    # ========================================================================
    # Grammar Rules (Top-Down Recursive Descent)
    # ========================================================================

    def _parse_program(self) -> ProcessAST:
        proc_tok = self._expect(TokenType.PROCESS)
        id_tok = self._expect_identifier_name()
        name_tok = self._match(TokenType.STRING)
        proc_name = name_tok.value if name_tok else id_tok.value

        self._expect(TokenType.LBRACE)
        lanes: List[LaneAST] = []
        nodes: List[NodeAST] = []

        while self._current().type != TokenType.RBRACE and self._current().type != TokenType.EOF:
            if self._current().type == TokenType.LANE:
                lanes.append(self._parse_lane())
            else:
                nodes.append(self._parse_node_decl(lane_name=None))

        self._expect(TokenType.RBRACE)
        return ProcessAST(
            process_id=id_tok.value,
            name=proc_name,
            lanes=lanes,
            nodes=nodes,
            line=proc_tok.line,
            column=proc_tok.column,
        )

    def _parse_lane(self) -> LaneAST:
        lane_tok = self._expect(TokenType.LANE)
        name_tok = self._expect(TokenType.STRING)
        self._expect(TokenType.LBRACE)
        lane_nodes: List[NodeAST] = []
        while self._current().type != TokenType.RBRACE and self._current().type != TokenType.EOF:
            lane_nodes.append(self._parse_node_decl(lane_name=name_tok.value))
        self._expect(TokenType.RBRACE)
        return LaneAST(
            name=name_tok.value,
            nodes=lane_nodes,
            line=lane_tok.line,
            column=lane_tok.column,
        )

    def _parse_node_decl(self, lane_name: Optional[str]) -> NodeAST:
        curr = self._current()
        if curr.type == TokenType.START:
            return self._parse_start_decl(lane_name)
        if curr.type == TokenType.END:
            return self._parse_end_decl(lane_name)
        if curr.type in TASK_TOKEN_TYPES:
            return self._parse_task_decl(lane_name)
        if curr.type in GATEWAY_TOKEN_TYPES:
            return self._parse_gateway_decl(lane_name)

        raise FlowSpecSyntaxError(
            f"Unexpected token '{curr.value}' ({curr.type.value}) where a node declaration was expected",
            curr.line,
            curr.column,
            curr.value,
        )

    def _parse_start_decl(self, lane_name: Optional[str]) -> TaskNodeAST:
        start_tok = self._expect(TokenType.START)
        id_tok = self._expect_identifier_name()
        name_tok = self._match(TokenType.STRING)
        node_name = name_tok.value if name_tok else id_tok.value

        node = TaskNodeAST(
            id=id_tok.value,
            name=node_name,
            kind="start",
            lane=lane_name,
            line=start_tok.line,
            column=start_tok.column,
        )

        if self._match(TokenType.LBRACE):
            self._parse_task_body(node)
            self._expect(TokenType.RBRACE)
        else:
            if self._match(TokenType.ARROW):
                target = self._expect_identifier_name()
                node.transitions.append(target.value)
            self._expect(TokenType.SEMICOLON)

        return node

    def _parse_end_decl(self, lane_name: Optional[str]) -> NodeAST:
        end_tok = self._expect(TokenType.END)
        id_tok = self._expect_identifier_name()
        name_tok = self._match(TokenType.STRING)
        node_name = name_tok.value if name_tok else id_tok.value
        self._expect(TokenType.SEMICOLON)
        return NodeAST(
            id=id_tok.value,
            name=node_name,
            kind="end",
            lane=lane_name,
            transitions=[],
            line=end_tok.line,
            column=end_tok.column,
        )

    def _parse_task_decl(self, lane_name: Optional[str]) -> TaskNodeAST:
        kind_tok = self._advance()
        id_tok = self._expect_identifier_name()
        name_tok = self._match(TokenType.STRING)
        node_name = name_tok.value if name_tok else id_tok.value

        node = TaskNodeAST(
            id=id_tok.value,
            name=node_name,
            kind=kind_tok.value,
            lane=lane_name,
            line=kind_tok.line,
            column=kind_tok.column,
        )

        self._expect(TokenType.LBRACE)
        self._parse_task_body(node)
        self._expect(TokenType.RBRACE)
        return node

    def _parse_task_body(self, node: TaskNodeAST) -> None:
        while self._current().type != TokenType.RBRACE and self._current().type != TokenType.EOF:
            curr = self._current()
            if curr.type == TokenType.FORM_FIELD:
                self._advance()
                fid = self._expect_identifier_name()
                self._expect(TokenType.COLON)
                ftype = self._expect_identifier_name()
                flabel_tok = self._match(TokenType.STRING)
                self._expect(TokenType.SEMICOLON)
                node.form_fields.append(
                    FormFieldAST(
                        name=fid.value,
                        field_type=ftype.value,
                        label=flabel_tok.value if flabel_tok else fid.value,
                        line=curr.line,
                        column=curr.column,
                    )
                )
            elif curr.type == TokenType.FORM_REF:
                self._advance()
                fref = self._expect(TokenType.STRING)
                self._expect(TokenType.SEMICOLON)
                node.form_ref = fref.value
            elif curr.type == TokenType.DELEGATE_CLASS:
                self._advance()
                dcls = self._expect(TokenType.STRING)
                self._expect(TokenType.SEMICOLON)
                node.delegate_class = dcls.value
            elif curr.type == TokenType.DECISION_REF:
                self._advance()
                dref = self._expect(TokenType.STRING)
                self._expect(TokenType.ARROW)
                rvar = self._expect_identifier_name()
                self._expect(TokenType.SEMICOLON)
                node.decision_ref = dref.value
                node.result_variable = rvar.value
            elif curr.type == TokenType.CALLED_ELEMENT:
                self._advance()
                celem = self._expect(TokenType.STRING)
                self._expect(TokenType.SEMICOLON)
                node.called_element = celem.value
            elif curr.type == TokenType.SCRIPT:
                self._advance()
                scr = self._expect(TokenType.STRING)
                self._expect(TokenType.SEMICOLON)
                node.script = scr.value
            elif curr.type in (TokenType.INPUT, TokenType.OUTPUT):
                dir_tok = self._advance()
                target_id = self._expect_identifier_name()
                self._expect(TokenType.LEFT_ARROW)
                expr = self._parse_expr()
                self._expect(TokenType.SEMICOLON)
                node.io_mappings.append(
                    IOMappingAST(
                        direction=dir_tok.value,
                        target=target_id.value,
                        expr=expr,
                        line=dir_tok.line,
                        column=dir_tok.column,
                    )
                )
            elif curr.type == TokenType.HTTP_CONNECTOR:
                node.http_connector = self._parse_http_connector()
            elif curr.type == TokenType.ARROW:
                self._advance()
                tgt = self._expect_identifier_name()
                self._expect(TokenType.SEMICOLON)
                node.transitions.append(tgt.value)
            else:
                raise FlowSpecSyntaxError(
                    f"Unexpected token '{curr.value}' inside task '{node.id}'",
                    curr.line,
                    curr.column,
                    curr.value,
                )

    def _parse_http_connector(self) -> HttpConnectorAST:
        hc_tok = self._expect(TokenType.HTTP_CONNECTOR)
        self._expect(TokenType.LBRACE)
        hc = HttpConnectorAST(line=hc_tok.line, column=hc_tok.column)

        while self._current().type != TokenType.RBRACE and self._current().type != TokenType.EOF:
            curr = self._current()
            if curr.type == TokenType.METHOD:
                self._advance()
                self._expect(TokenType.COLON)
                m_tok = self._expect(TokenType.STRING)
                self._expect(TokenType.SEMICOLON)
                hc.method = m_tok.value
            elif curr.type == TokenType.URL:
                self._advance()
                self._expect(TokenType.COLON)
                u_tok = self._expect(TokenType.STRING)
                self._expect(TokenType.SEMICOLON)
                hc.url = u_tok.value
            elif curr.type == TokenType.HEADERS:
                self._advance()
                self._expect(TokenType.COLON)
                self._expect(TokenType.LBRACE)
                while self._current().type != TokenType.RBRACE:
                    k_tok = self._expect(TokenType.STRING)
                    self._expect(TokenType.COLON)
                    v_tok = self._expect(TokenType.STRING)
                    hc.headers[k_tok.value] = v_tok.value
                    self._match(TokenType.COMMA)
                self._expect(TokenType.RBRACE)
                self._expect(TokenType.SEMICOLON)
            elif curr.type == TokenType.PAYLOAD:
                self._advance()
                self._expect(TokenType.COLON)
                self._expect(TokenType.LBRACE)
                while self._current().type != TokenType.RBRACE:
                    k_tok = self._expect(TokenType.STRING)
                    self._expect(TokenType.COLON)
                    val_expr = self._parse_expr()
                    hc.payload_fields[k_tok.value] = val_expr
                    self._match(TokenType.COMMA)
                self._expect(TokenType.RBRACE)
                self._expect(TokenType.SEMICOLON)
            elif curr.type == TokenType.OUTPUT:
                self._advance()
                self._expect(TokenType.COLON)
                out_tgt = self._expect_identifier_name()
                self._expect(TokenType.LEFT_ARROW)
                out_src = self._expect_identifier_name()
                self._expect(TokenType.SEMICOLON)
                hc.output_target = out_tgt.value
                hc.output_source = out_src.value
            else:
                raise FlowSpecSyntaxError(
                    f"Unexpected token '{curr.value}' inside http_connector",
                    curr.line,
                    curr.column,
                    curr.value,
                )

        self._expect(TokenType.RBRACE)
        return hc

    def _parse_gateway_decl(self, lane_name: Optional[str]) -> GatewayAST:
        gw_tok = self._advance()
        id_tok = self._expect_identifier_name()
        name_tok = self._match(TokenType.STRING)
        node_name = name_tok.value if name_tok else id_tok.value

        self._expect(TokenType.LBRACE)
        branches: List[GatewayBranchAST] = []
        transitions: List[str] = []

        while self._current().type != TokenType.RBRACE and self._current().type != TokenType.EOF:
            curr = self._current()
            if curr.type == TokenType.WHEN:
                self._advance()
                self._expect(TokenType.LPAREN)
                cond = self._parse_expr()
                self._expect(TokenType.RPAREN)
                self._expect(TokenType.ARROW)
                tgt = self._expect_identifier_name()
                self._expect(TokenType.SEMICOLON)
                branches.append(
                    GatewayBranchAST(
                        branch_kind="when",
                        target_id=tgt.value,
                        condition=cond,
                        line=curr.line,
                        column=curr.column,
                    )
                )
                transitions.append(tgt.value)
            elif curr.type == TokenType.DEFAULT:
                self._advance()
                self._expect(TokenType.ARROW)
                tgt = self._expect_identifier_name()
                self._expect(TokenType.SEMICOLON)
                branches.append(
                    GatewayBranchAST(
                        branch_kind="default",
                        target_id=tgt.value,
                        condition=None,
                        line=curr.line,
                        column=curr.column,
                    )
                )
                transitions.append(tgt.value)
            elif curr.type == TokenType.BRANCH:
                self._advance()
                self._expect(TokenType.ARROW)
                tgt = self._expect_identifier_name()
                self._expect(TokenType.SEMICOLON)
                branches.append(
                    GatewayBranchAST(
                        branch_kind="branch",
                        target_id=tgt.value,
                        condition=None,
                        line=curr.line,
                        column=curr.column,
                    )
                )
                transitions.append(tgt.value)
            elif curr.type == TokenType.ARROW:
                self._advance()
                tgt = self._expect_identifier_name()
                self._expect(TokenType.SEMICOLON)
                branches.append(
                    GatewayBranchAST(
                        branch_kind="branch",
                        target_id=tgt.value,
                        condition=None,
                        line=curr.line,
                        column=curr.column,
                    )
                )
                transitions.append(tgt.value)
            else:
                raise FlowSpecSyntaxError(
                    f"Unexpected token '{curr.value}' inside gateway '{id_tok.value}'",
                    curr.line,
                    curr.column,
                    curr.value,
                )

        self._expect(TokenType.RBRACE)
        return GatewayAST(
            id=id_tok.value,
            name=node_name,
            kind=gw_tok.value,
            lane=lane_name,
            transitions=transitions,
            branches=branches,
            line=gw_tok.line,
            column=gw_tok.column,
        )

    # ========================================================================
    # Expression Precedence Hierarchy (LL(1))
    # ========================================================================

    def _parse_expr(self) -> ExprAST:
        return self._parse_logical_or()

    def _parse_logical_or(self) -> ExprAST:
        left = self._parse_logical_and()
        while tok := self._match(TokenType.OP_OR):
            right = self._parse_logical_and()
            left = BinaryExprAST(operator="||", left=left, right=right, line=tok.line, column=tok.column)
        return left

    def _parse_logical_and(self) -> ExprAST:
        left = self._parse_equality()
        while tok := self._match(TokenType.OP_AND):
            right = self._parse_equality()
            left = BinaryExprAST(operator="&&", left=left, right=right, line=tok.line, column=tok.column)
        return left

    def _parse_equality(self) -> ExprAST:
        left = self._parse_comparison()
        while tok := self._match(TokenType.OP_EQ, TokenType.OP_NEQ):
            right = self._parse_comparison()
            left = BinaryExprAST(
                operator=tok.value, left=left, right=right, line=tok.line, column=tok.column
            )
        return left

    def _parse_comparison(self) -> ExprAST:
        left = self._parse_term()
        while tok := self._match(TokenType.OP_LT, TokenType.OP_LTE, TokenType.OP_GT, TokenType.OP_GTE):
            right = self._parse_term()
            left = BinaryExprAST(
                operator=tok.value, left=left, right=right, line=tok.line, column=tok.column
            )
        return left

    def _parse_term(self) -> ExprAST:
        left = self._parse_factor()
        while tok := self._match(TokenType.OP_PLUS, TokenType.OP_MINUS):
            right = self._parse_factor()
            left = BinaryExprAST(
                operator=tok.value, left=left, right=right, line=tok.line, column=tok.column
            )
        return left

    def _parse_factor(self) -> ExprAST:
        left = self._parse_unary()
        while tok := self._match(TokenType.OP_MUL, TokenType.OP_DIV):
            right = self._parse_unary()
            left = BinaryExprAST(
                operator=tok.value, left=left, right=right, line=tok.line, column=tok.column
            )
        return left

    def _parse_unary(self) -> ExprAST:
        if tok := self._match(TokenType.OP_NOT, TokenType.OP_MINUS):
            op_str = "!" if tok.type == TokenType.OP_NOT else "-"
            operand = self._parse_unary()
            return UnaryExprAST(operator=op_str, operand=operand, line=tok.line, column=tok.column)
        return self._parse_primary()

    def _parse_primary(self) -> ExprAST:
        tok = self._current()
        if self._match(TokenType.LPAREN):
            expr = self._parse_expr()
            self._expect(TokenType.RPAREN)
            return expr
        if self._match(TokenType.BOOLEAN):
            return LiteralAST(
                value=(tok.value.lower() == "true"),
                literal_type="boolean",
                line=tok.line,
                column=tok.column,
            )
        if self._match(TokenType.NUMBER):
            num_val: int | float = float(tok.value) if "." in tok.value else int(tok.value)
            return LiteralAST(value=num_val, literal_type="number", line=tok.line, column=tok.column)
        if self._match(TokenType.STRING):
            return LiteralAST(value=tok.value, literal_type="string", line=tok.line, column=tok.column)
        if tok.type in IDENTIFIER_LIKE_TOKENS:
            self._advance()
            return IdentifierAST(name=tok.value, line=tok.line, column=tok.column)

        raise FlowSpecSyntaxError(
            f"Unexpected token '{tok.value}' ({tok.type.value}) in expression",
            tok.line,
            tok.column,
            tok.value,
        )

