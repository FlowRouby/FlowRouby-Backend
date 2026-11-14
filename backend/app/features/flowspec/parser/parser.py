"""Vanilla Python Top-Down Recursive Descent Parser LL(1) (Chomsky Type 2 CFG) for FlowSpec DSL."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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

IDENTIFIER_LIKE_TOKENS = {
    TokenType.IDENTIFIER,
    TokenType.PROCESS,
    TokenType.LANE,
    TokenType.START,
    TokenType.END,
    TokenType.USER,
    TokenType.SERVICE,
    TokenType.SCRIPT,
    TokenType.MANUAL,
    TokenType.BUSINESS,
    TokenType.RULE,
    TokenType.CALL,
    TokenType.ACTIVITY,
    TokenType.TASK,
    TokenType.DECISION,
    TokenType.PARALLEL,
    TokenType.INCLUSIVE,
    TokenType.SPLIT,
    TokenType.ASK,
    TokenType.LABELED,
    TokenType.USE,
    TokenType.FORM,
    TokenType.DELEGATE,
    TokenType.DECIDE,
    TokenType.INTO,
    TokenType.SET,
    TokenType.INPUT,
    TokenType.OUTPUT,
    TokenType.RUN,
    TokenType.HTTP,
    TokenType.METHOD,
    TokenType.URL,
    TokenType.HEADERS,
    TokenType.PAYLOAD,
    TokenType.WITH,
    TokenType.SAVE,
    TokenType.FROM,
    TokenType.NEXT,
    TokenType.IF,
    TokenType.OTHERWISE,
    TokenType.GO,
    TokenType.TO,
    TokenType.BRANCH,
}


class FlowSpecSyntaxError(Exception):
    """Raised when the FlowSpec LL(1) parser encounters an unexpected token."""

    def __init__(self, message: str, line: int, column: int, token_value: str = ""):
        super().__init__(f"[Line {line}, Col {column}] SyntaxError: {message}")
        self.message = message
        self.line = line
        self.column = column
        self.token_value = token_value


class FlowSpecParser:
    """LL(1) Recursive Descent Parser for natural indentation-based FlowSpec DSL."""

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

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _peek(self, offset: int = 1) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]

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

    def _parse_name_and_id(self) -> Tuple[str, str]:
        name_tok = self._match(TokenType.STRING)
        if name_tok is not None:
            self._expect(TokenType.AS)
            id_tok = self._expect_identifier_name()
            return name_tok.value, id_tok.value
        id_tok = self._expect_identifier_name()
        return id_tok.value, id_tok.value

    def _parse_program(self) -> ProcessAST:
        proc_tok = self._expect(TokenType.PROCESS)
        display_name, process_id = self._parse_name_and_id()
        self._expect(TokenType.NEWLINE)

        lanes: List[LaneAST] = []
        nodes: List[NodeAST] = []

        if self._match(TokenType.INDENT):
            while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
                if self._current().type == TokenType.LANE:
                    lanes.append(self._parse_lane())
                else:
                    nodes.append(self._parse_node(lane=None))
            self._expect(TokenType.DEDENT)

        return ProcessAST(
            process_id=process_id,
            name=display_name,
            lanes=lanes,
            nodes=nodes,
            line=proc_tok.line,
            column=proc_tok.column,
        )

    def _parse_lane(self) -> LaneAST:
        lane_tok = self._expect(TokenType.LANE)
        name_tok = self._expect(TokenType.STRING)
        self._expect(TokenType.NEWLINE)
        lane_nodes: List[NodeAST] = []
        if self._match(TokenType.INDENT):
            while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
                lane_nodes.append(self._parse_node(lane=name_tok.value))
            self._expect(TokenType.DEDENT)
        return LaneAST(
            name=name_tok.value,
            nodes=lane_nodes,
            line=lane_tok.line,
            column=lane_tok.column,
        )

    def _parse_node(self, lane: Optional[str]) -> NodeAST:
        tok = self._current()
        if tok.type == TokenType.START:
            return self._parse_start(lane)
        if tok.type == TokenType.END:
            return self._parse_end(lane)
        if tok.type in (
            TokenType.USER,
            TokenType.SERVICE,
            TokenType.SCRIPT,
            TokenType.MANUAL,
            TokenType.BUSINESS,
            TokenType.CALL,
        ):
            return self._parse_task(lane)
        if tok.type in (TokenType.DECISION, TokenType.PARALLEL, TokenType.INCLUSIVE):
            return self._parse_gateway(lane)
        raise FlowSpecSyntaxError(
            f"Unexpected token '{tok.value}' ({tok.type.value}) while parsing flow node.",
            tok.line,
            tok.column,
            tok.value,
        )

    def _parse_start(self, lane: Optional[str]) -> TaskNodeAST:
        start_tok = self._expect(TokenType.START)
        display_name, node_id = self._parse_name_and_id()
        self._expect(TokenType.NEWLINE)

        task = TaskNodeAST(
            id=node_id,
            name=display_name,
            kind="start",
            lane=lane,
            line=start_tok.line,
            column=start_tok.column,
        )
        if self._match(TokenType.INDENT):
            while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
                self._parse_task_attribute(task)
            self._expect(TokenType.DEDENT)
        return task

    def _parse_end(self, lane: Optional[str]) -> NodeAST:
        end_tok = self._expect(TokenType.END)
        display_name, node_id = self._parse_name_and_id()
        self._expect(TokenType.NEWLINE)
        return NodeAST(
            id=node_id,
            name=display_name,
            kind="end",
            lane=lane,
            line=end_tok.line,
            column=end_tok.column,
        )

    def _parse_task_kind(self) -> Tuple[Token, str]:
        tok = self._advance()
        if tok.type == TokenType.USER:
            self._expect(TokenType.TASK)
            return tok, "user_task"
        if tok.type == TokenType.SERVICE:
            self._expect(TokenType.TASK)
            return tok, "service_task"
        if tok.type == TokenType.SCRIPT:
            self._expect(TokenType.TASK)
            return tok, "script_task"
        if tok.type == TokenType.MANUAL:
            self._expect(TokenType.TASK)
            return tok, "manual_task"
        if tok.type == TokenType.BUSINESS:
            self._expect(TokenType.RULE)
            return tok, "business_rule_task"
        self._expect(TokenType.ACTIVITY)
        return tok, "call_activity"

    def _parse_task(self, lane: Optional[str]) -> TaskNodeAST:
        kind_tok, kind = self._parse_task_kind()
        display_name, node_id = self._parse_name_and_id()
        self._expect(TokenType.NEWLINE)

        task = TaskNodeAST(
            id=node_id,
            name=display_name,
            kind=kind,
            lane=lane,
            line=kind_tok.line,
            column=kind_tok.column,
        )

        if self._match(TokenType.INDENT):
            while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
                self._parse_task_attribute(task)
            self._expect(TokenType.DEDENT)

        return task

    def _parse_task_attribute(self, task: TaskNodeAST) -> None:
        tok = self._current()

        if tok.type == TokenType.ASK:
            self._advance()
            type_tok = self._expect_identifier_name()
            field_name_tok = self._expect_identifier_name()
            label = field_name_tok.value
            if self._match(TokenType.LABELED):
                label = self._expect(TokenType.STRING).value
            self._expect(TokenType.NEWLINE)
            task.form_fields.append(
                FormFieldAST(
                    name=field_name_tok.value,
                    field_type=type_tok.value,
                    label=label,
                    line=tok.line,
                    column=tok.column,
                )
            )
            return

        if tok.type == TokenType.USE:
            self._advance()
            self._expect(TokenType.FORM)
            task.form_ref = self._expect(TokenType.STRING).value
            self._expect(TokenType.NEWLINE)
            return

        if tok.type == TokenType.DELEGATE:
            self._advance()
            task.delegate_class = self._expect(TokenType.STRING).value
            self._expect(TokenType.NEWLINE)
            return

        if tok.type == TokenType.DECIDE:
            self._advance()
            task.decision_ref = self._expect(TokenType.STRING).value
            self._expect(TokenType.INTO)
            task.result_variable = self._expect_identifier_name().value
            self._expect(TokenType.NEWLINE)
            return

        if tok.type == TokenType.CALL:
            self._advance()
            task.called_element = self._expect(TokenType.STRING).value
            self._expect(TokenType.NEWLINE)
            return

        if tok.type == TokenType.RUN:
            self._advance()
            self._expect(TokenType.SCRIPT)
            task.script = self._expect(TokenType.STRING).value
            self._expect(TokenType.NEWLINE)
            return

        if tok.type == TokenType.SET:
            self._advance()
            if self._match(TokenType.INPUT):
                direction = "input"
            elif self._match(TokenType.OUTPUT):
                direction = "output"
            else:
                bad = self._current()
                raise FlowSpecSyntaxError(
                    f"Expected 'input' or 'output' after 'set', got '{bad.value}'",
                    bad.line,
                    bad.column,
                    bad.value,
                )
            target_tok = self._expect_identifier_name()
            self._expect(TokenType.FROM)
            expr = self._parse_expr()
            self._expect(TokenType.NEWLINE)
            task.io_mappings.append(
                IOMappingAST(
                    direction=direction,
                    target=target_tok.value,
                    expr=expr,
                    line=tok.line,
                    column=tok.column,
                )
            )
            return

        if tok.type == TokenType.HTTP:
            task.http_connector = self._parse_http_connector()
            return

        if tok.type == TokenType.NEXT:
            self._advance()
            self._expect(TokenType.IS)
            target_tok = self._expect_identifier_name()
            self._expect(TokenType.NEWLINE)
            task.transitions.append(target_tok.value)
            return

        raise FlowSpecSyntaxError(
            f"Unexpected token '{tok.value}' inside task '{task.id}'.",
            tok.line,
            tok.column,
            tok.value,
        )

    def _parse_http_connector(self) -> HttpConnectorAST:
        http_tok = self._expect(TokenType.HTTP)
        self._expect(TokenType.CALL)
        self._expect(TokenType.NEWLINE)
        self._expect(TokenType.INDENT)

        method = "GET"
        url = ""
        headers: Dict[str, str] = {}
        payload_fields: Dict[str, ExprAST] = {}
        output_target: Optional[str] = None
        output_source: Optional[str] = None

        while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
            attr_tok = self._current()
            if attr_tok.type == TokenType.METHOD:
                self._advance()
                method = self._expect(TokenType.STRING).value.upper()
                self._expect(TokenType.NEWLINE)
            elif attr_tok.type == TokenType.URL:
                self._advance()
                url = self._expect(TokenType.STRING).value
                self._expect(TokenType.NEWLINE)
            elif attr_tok.type == TokenType.HEADERS:
                self._advance()
                self._expect(TokenType.NEWLINE)
                self._expect(TokenType.INDENT)
                while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
                    k = self._expect(TokenType.STRING).value
                    self._expect(TokenType.IS)
                    v = self._expect(TokenType.STRING).value
                    self._expect(TokenType.NEWLINE)
                    headers[k] = v
                self._expect(TokenType.DEDENT)
            elif attr_tok.type == TokenType.PAYLOAD:
                self._advance()
                self._expect(TokenType.NEWLINE)
                self._expect(TokenType.INDENT)
                while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
                    k = self._expect(TokenType.STRING).value
                    self._expect(TokenType.FROM)
                    v_expr = self._parse_expr()
                    self._expect(TokenType.NEWLINE)
                    payload_fields[k] = v_expr
                self._expect(TokenType.DEDENT)
            elif attr_tok.type == TokenType.SAVE:
                self._advance()
                output_source = self._expect_identifier_name().value
                self._expect(TokenType.AS)
                output_target = self._expect_identifier_name().value
                self._expect(TokenType.NEWLINE)
            else:
                raise FlowSpecSyntaxError(
                    f"Unexpected token '{attr_tok.value}' inside http call block.",
                    attr_tok.line,
                    attr_tok.column,
                    attr_tok.value,
                )

        self._expect(TokenType.DEDENT)
        return HttpConnectorAST(
            method=method,
            url=url,
            headers=headers,
            payload_fields=payload_fields,
            output_target=output_target,
            output_source=output_source,
            line=http_tok.line,
            column=http_tok.column,
        )

    def _parse_gateway_kind(self) -> Tuple[Token, str]:
        tok = self._advance()
        if tok.type == TokenType.DECISION:
            return tok, "exclusive_gateway"
        if tok.type == TokenType.PARALLEL:
            self._expect(TokenType.SPLIT)
            return tok, "parallel_gateway"
        self._expect(TokenType.SPLIT)
        return tok, "inclusive_gateway"

    def _parse_gateway(self, lane: Optional[str]) -> GatewayAST:
        gw_tok, gw_kind = self._parse_gateway_kind()
        display_name, node_id = self._parse_name_and_id()
        self._expect(TokenType.NEWLINE)

        branches: List[GatewayBranchAST] = []
        transitions: List[str] = []

        if self._match(TokenType.INDENT):
            while self._current().type not in (TokenType.DEDENT, TokenType.EOF):
                b_tok = self._current()
                if b_tok.type == TokenType.IF:
                    self._advance()
                    cond_expr = self._parse_expr()
                    self._expect(TokenType.GO)
                    self._expect(TokenType.TO)
                    target_tok = self._expect_identifier_name()
                    self._expect(TokenType.NEWLINE)
                    branches.append(
                        GatewayBranchAST(
                            branch_kind="when",
                            target_id=target_tok.value,
                            condition=cond_expr,
                            line=b_tok.line,
                            column=b_tok.column,
                        )
                    )
                    transitions.append(target_tok.value)
                elif b_tok.type == TokenType.OTHERWISE:
                    self._advance()
                    self._expect(TokenType.GO)
                    self._expect(TokenType.TO)
                    target_tok = self._expect_identifier_name()
                    self._expect(TokenType.NEWLINE)
                    branches.append(
                        GatewayBranchAST(
                            branch_kind="default",
                            target_id=target_tok.value,
                            line=b_tok.line,
                            column=b_tok.column,
                        )
                    )
                    transitions.append(target_tok.value)
                elif b_tok.type == TokenType.BRANCH:
                    self._advance()
                    self._expect(TokenType.TO)
                    target_tok = self._expect_identifier_name()
                    self._expect(TokenType.NEWLINE)
                    branches.append(
                        GatewayBranchAST(
                            branch_kind="branch",
                            target_id=target_tok.value,
                            line=b_tok.line,
                            column=b_tok.column,
                        )
                    )
                    transitions.append(target_tok.value)
                elif b_tok.type == TokenType.NEXT:
                    self._advance()
                    self._expect(TokenType.IS)
                    target_tok = self._expect_identifier_name()
                    self._expect(TokenType.NEWLINE)
                    branches.append(
                        GatewayBranchAST(
                            branch_kind="branch",
                            target_id=target_tok.value,
                            line=b_tok.line,
                            column=b_tok.column,
                        )
                    )
                    transitions.append(target_tok.value)
                else:
                    raise FlowSpecSyntaxError(
                        f"Unexpected token '{b_tok.value}' inside gateway '{node_id}'.",
                        b_tok.line,
                        b_tok.column,
                        b_tok.value,
                    )
            self._expect(TokenType.DEDENT)

        return GatewayAST(
            id=node_id,
            name=display_name,
            kind=gw_kind,
            lane=lane,
            transitions=transitions,
            branches=branches,
            line=gw_tok.line,
            column=gw_tok.column,
        )

    def _parse_expr(self) -> ExprAST:
        return self._parse_logical_or()

    def _parse_logical_or(self) -> ExprAST:
        left = self._parse_logical_and()
        while self._current().type == TokenType.OP_OR:
            op_tok = self._advance()
            right = self._parse_logical_and()
            left = BinaryExprAST(
                operator="||", left=left, right=right, line=op_tok.line, column=op_tok.column
            )
        return left

    def _parse_logical_and(self) -> ExprAST:
        left = self._parse_equality()
        while self._current().type == TokenType.OP_AND:
            op_tok = self._advance()
            right = self._parse_equality()
            left = BinaryExprAST(
                operator="&&", left=left, right=right, line=op_tok.line, column=op_tok.column
            )
        return left

    def _parse_equality(self) -> ExprAST:
        left = self._parse_comparison()
        while self._current().type == TokenType.IS:
            op_tok = self._advance()
            operator = "!=" if self._match(TokenType.OP_NOT) else "=="
            right = self._parse_comparison()
            left = BinaryExprAST(
                operator=operator, left=left, right=right, line=op_tok.line, column=op_tok.column
            )
        return left

    def _parse_comparison(self) -> ExprAST:
        left = self._parse_term()
        while self._current().type in (
            TokenType.OP_LT,
            TokenType.OP_LTE,
            TokenType.OP_GT,
            TokenType.OP_GTE,
        ):
            op_tok = self._advance()
            right = self._parse_term()
            left = BinaryExprAST(
                operator=op_tok.value, left=left, right=right, line=op_tok.line, column=op_tok.column
            )
        return left

    def _parse_term(self) -> ExprAST:
        left = self._parse_factor()
        while self._current().type in (TokenType.OP_PLUS, TokenType.OP_MINUS):
            op_tok = self._advance()
            right = self._parse_factor()
            left = BinaryExprAST(
                operator=op_tok.value, left=left, right=right, line=op_tok.line, column=op_tok.column
            )
        return left

    def _parse_factor(self) -> ExprAST:
        left = self._parse_unary()
        while self._current().type in (TokenType.OP_MUL, TokenType.OP_DIV):
            op_tok = self._advance()
            right = self._parse_unary()
            left = BinaryExprAST(
                operator=op_tok.value, left=left, right=right, line=op_tok.line, column=op_tok.column
            )
        return left

    def _parse_unary(self) -> ExprAST:
        if self._current().type in (TokenType.OP_NOT, TokenType.OP_MINUS):
            op_tok = self._advance()
            operand = self._parse_unary()
            op = "!" if op_tok.type == TokenType.OP_NOT else "-"
            return UnaryExprAST(operator=op, operand=operand, line=op_tok.line, column=op_tok.column)
        return self._parse_primary()

    def _parse_primary(self) -> ExprAST:
        tok = self._current()
        if tok.type == TokenType.NUMBER:
            self._advance()
            val = float(tok.value) if "." in tok.value else int(tok.value)
            return LiteralAST(value=val, literal_type="number", line=tok.line, column=tok.column)
        if tok.type == TokenType.STRING:
            self._advance()
            return LiteralAST(value=tok.value, literal_type="string", line=tok.line, column=tok.column)
        if tok.type == TokenType.BOOLEAN:
            self._advance()
            return LiteralAST(
                value=(tok.value == "true"), literal_type="boolean", line=tok.line, column=tok.column
            )
        if tok.type in IDENTIFIER_LIKE_TOKENS:
            self._advance()
            return IdentifierAST(name=tok.value, line=tok.line, column=tok.column)
        if tok.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenType.RPAREN)
            return expr
        raise FlowSpecSyntaxError(
            f"Unexpected token '{tok.value}' ({tok.type.value}) in expression.",
            tok.line,
            tok.column,
            tok.value,
        )
