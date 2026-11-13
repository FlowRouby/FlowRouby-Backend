"""Vanilla Python Lexical Analyzer (Chomsky Type 3 Regular Expression Scanner) for FlowSpec DSL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class TokenType(str, Enum):
    PROCESS = "PROCESS"
    LANE = "LANE"
    START = "START"
    END = "END"
    USER_TASK = "USER_TASK"
    SERVICE_TASK = "SERVICE_TASK"
    SCRIPT_TASK = "SCRIPT_TASK"
    MANUAL_TASK = "MANUAL_TASK"
    BUSINESS_RULE_TASK = "BUSINESS_RULE_TASK"
    CALL_ACTIVITY = "CALL_ACTIVITY"
    EXCLUSIVE_GATEWAY = "EXCLUSIVE_GATEWAY"
    PARALLEL_GATEWAY = "PARALLEL_GATEWAY"
    INCLUSIVE_GATEWAY = "INCLUSIVE_GATEWAY"

    FORM_FIELD = "FORM_FIELD"
    FORM_REF = "FORM_REF"
    DELEGATE_CLASS = "DELEGATE_CLASS"
    DECISION_REF = "DECISION_REF"
    CALLED_ELEMENT = "CALLED_ELEMENT"
    SCRIPT = "SCRIPT"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    HTTP_CONNECTOR = "HTTP_CONNECTOR"
    METHOD = "METHOD"
    URL = "URL"
    HEADERS = "HEADERS"
    PAYLOAD = "PAYLOAD"

    WHEN = "WHEN"
    DEFAULT = "DEFAULT"
    BRANCH = "BRANCH"

    IDENTIFIER = "IDENTIFIER"
    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"

    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COLON = "COLON"
    SEMICOLON = "SEMICOLON"
    COMMA = "COMMA"
    ARROW = "ARROW"
    LEFT_ARROW = "LEFT_ARROW"

    OP_EQ = "OP_EQ"
    OP_NEQ = "OP_NEQ"
    OP_LTE = "OP_LTE"
    OP_GTE = "OP_GTE"
    OP_LT = "OP_LT"
    OP_GT = "OP_GT"
    OP_AND = "OP_AND"
    OP_OR = "OP_OR"
    OP_NOT = "OP_NOT"
    OP_PLUS = "OP_PLUS"
    OP_MINUS = "OP_MINUS"
    OP_MUL = "OP_MUL"
    OP_DIV = "OP_DIV"

    EOF = "EOF"


KEYWORDS: Dict[str, TokenType] = {
    "process": TokenType.PROCESS,
    "lane": TokenType.LANE,
    "start": TokenType.START,
    "end": TokenType.END,
    "user_task": TokenType.USER_TASK,
    "service_task": TokenType.SERVICE_TASK,
    "script_task": TokenType.SCRIPT_TASK,
    "manual_task": TokenType.MANUAL_TASK,
    "business_rule_task": TokenType.BUSINESS_RULE_TASK,
    "call_activity": TokenType.CALL_ACTIVITY,
    "exclusive_gateway": TokenType.EXCLUSIVE_GATEWAY,
    "parallel_gateway": TokenType.PARALLEL_GATEWAY,
    "inclusive_gateway": TokenType.INCLUSIVE_GATEWAY,
    "form_field": TokenType.FORM_FIELD,
    "form_ref": TokenType.FORM_REF,
    "delegate_class": TokenType.DELEGATE_CLASS,
    "decision_ref": TokenType.DECISION_REF,
    "called_element": TokenType.CALLED_ELEMENT,
    "script": TokenType.SCRIPT,
    "input": TokenType.INPUT,
    "output": TokenType.OUTPUT,
    "http_connector": TokenType.HTTP_CONNECTOR,
    "method": TokenType.METHOD,
    "url": TokenType.URL,
    "headers": TokenType.HEADERS,
    "payload": TokenType.PAYLOAD,
    "when": TokenType.WHEN,
    "default": TokenType.DEFAULT,
    "branch": TokenType.BRANCH,
    "true": TokenType.BOOLEAN,
    "false": TokenType.BOOLEAN,
    "and": TokenType.OP_AND,
    "or": TokenType.OP_OR,
    "not": TokenType.OP_NOT,
}


@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    column: int

    def to_dict(self) -> Dict[str, str | int]:
        return {
            "type": self.type.value,
            "value": self.value,
            "line": self.line,
            "column": self.column,
        }


class FlowSpecLexicalError(Exception):
    """Raised when the FlowSpec lexer encounters an illegal character or unterminated string."""

    def __init__(self, message: str, line: int, column: int):
        super().__init__(f"[Line {line}, Col {column}] LexicalError: {message}")
        self.message = message
        self.line = line
        self.column = column


TOKEN_SPECIFICATION = [
    ("COMMENT", r"//[^\n]*|#[^\n]*"),
    ("NEWLINE", r"\n"),
    ("SKIP", r"[ \t\r]+"),
    ("ARROW", r"->"),
    ("LEFT_ARROW", r"<-"),
    ("OP_EQ", r"=="),
    ("OP_NEQ", r"!="),
    ("OP_LTE", r"<="),
    ("OP_GTE", r">="),
    ("OP_AND", r"&&"),
    ("OP_OR", r"\|\|"),
    ("OP_LT", r"<"),
    ("OP_GT", r">"),
    ("OP_NOT", r"!"),
    ("OP_PLUS", r"\+"),
    ("OP_MINUS", r"-"),
    ("OP_MUL", r"\*"),
    ("OP_DIV", r"/"),
    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("COLON", r":"),
    ("SEMICOLON", r";"),
    ("COMMA", r","),
    ("STRING", r'"(?:\\.|[^"\\])*"'),
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("IDENTIFIER", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("MISMATCH", r"."),
]

MASTER_REGEX = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPECIFICATION)
)


class FlowSpecLexer:
    """Tokenizes FlowSpec DSL source code into a stream of Tokens."""

    def tokenize(self, source_code: str) -> List[Token]:
        tokens: List[Token] = []
        line_num = 1
        line_start = 0

        for match in MASTER_REGEX.finditer(source_code):
            kind = match.lastgroup
            value = match.group()
            column = match.start() - line_start + 1

            if kind == "NEWLINE":
                line_start = match.end()
                line_num += 1
                continue
            if kind in ("SKIP", "COMMENT"):
                continue
            if kind == "MISMATCH":
                raise FlowSpecLexicalError(
                    f"Unexpected character '{value}'", line=line_num, column=column
                )

            if kind == "STRING":
                unquoted = value[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
                tokens.append(Token(TokenType.STRING, unquoted, line_num, column))
            elif kind == "IDENTIFIER":
                token_type = KEYWORDS.get(value, TokenType.IDENTIFIER)
                tokens.append(Token(token_type, value, line_num, column))
            else:
                tokens.append(Token(TokenType[kind], value, line_num, column))

        tokens.append(Token(TokenType.EOF, "", line_num, len(source_code) - line_start + 1))
        return tokens

