"""Vanilla Python Lexical Analyzer (Chomsky Type 3 Scanner with strict indentation) for FlowSpec DSL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class TokenType(str, Enum):
    PROCESS = "PROCESS"
    LANE = "LANE"
    AS = "AS"
    START = "START"
    END = "END"
    USER = "USER"
    SERVICE = "SERVICE"
    SCRIPT = "SCRIPT"
    MANUAL = "MANUAL"
    BUSINESS = "BUSINESS"
    RULE = "RULE"
    CALL = "CALL"
    ACTIVITY = "ACTIVITY"
    TASK = "TASK"
    DECISION = "DECISION"
    PARALLEL = "PARALLEL"
    INCLUSIVE = "INCLUSIVE"
    SPLIT = "SPLIT"

    ASK = "ASK"
    LABELED = "LABELED"
    USE = "USE"
    FORM = "FORM"
    DELEGATE = "DELEGATE"
    DECIDE = "DECIDE"
    INTO = "INTO"
    SET = "SET"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    RUN = "RUN"
    HTTP = "HTTP"
    METHOD = "METHOD"
    URL = "URL"
    HEADERS = "HEADERS"
    PAYLOAD = "PAYLOAD"
    WITH = "WITH"
    SAVE = "SAVE"
    FROM = "FROM"
    NEXT = "NEXT"

    IF = "IF"
    OTHERWISE = "OTHERWISE"
    GO = "GO"
    TO = "TO"
    BRANCH = "BRANCH"

    IS = "IS"
    OP_AND = "OP_AND"
    OP_OR = "OP_OR"
    OP_NOT = "OP_NOT"
    OP_LTE = "OP_LTE"
    OP_GTE = "OP_GTE"
    OP_LT = "OP_LT"
    OP_GT = "OP_GT"
    OP_PLUS = "OP_PLUS"
    OP_MINUS = "OP_MINUS"
    OP_MUL = "OP_MUL"
    OP_DIV = "OP_DIV"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"

    IDENTIFIER = "IDENTIFIER"
    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"

    INDENT = "INDENT"
    DEDENT = "DEDENT"
    NEWLINE = "NEWLINE"
    EOF = "EOF"


KEYWORDS: Dict[str, TokenType] = {
    "process": TokenType.PROCESS,
    "lane": TokenType.LANE,
    "as": TokenType.AS,
    "start": TokenType.START,
    "end": TokenType.END,
    "user": TokenType.USER,
    "service": TokenType.SERVICE,
    "script": TokenType.SCRIPT,
    "manual": TokenType.MANUAL,
    "business": TokenType.BUSINESS,
    "rule": TokenType.RULE,
    "call": TokenType.CALL,
    "activity": TokenType.ACTIVITY,
    "task": TokenType.TASK,
    "decision": TokenType.DECISION,
    "parallel": TokenType.PARALLEL,
    "inclusive": TokenType.INCLUSIVE,
    "split": TokenType.SPLIT,
    "ask": TokenType.ASK,
    "labeled": TokenType.LABELED,
    "use": TokenType.USE,
    "form": TokenType.FORM,
    "delegate": TokenType.DELEGATE,
    "decide": TokenType.DECIDE,
    "into": TokenType.INTO,
    "set": TokenType.SET,
    "input": TokenType.INPUT,
    "output": TokenType.OUTPUT,
    "run": TokenType.RUN,
    "http": TokenType.HTTP,
    "method": TokenType.METHOD,
    "url": TokenType.URL,
    "headers": TokenType.HEADERS,
    "payload": TokenType.PAYLOAD,
    "with": TokenType.WITH,
    "save": TokenType.SAVE,
    "from": TokenType.FROM,
    "next": TokenType.NEXT,
    "if": TokenType.IF,
    "otherwise": TokenType.OTHERWISE,
    "go": TokenType.GO,
    "to": TokenType.TO,
    "branch": TokenType.BRANCH,
    "is": TokenType.IS,
    "and": TokenType.OP_AND,
    "or": TokenType.OP_OR,
    "not": TokenType.OP_NOT,
    "true": TokenType.BOOLEAN,
    "false": TokenType.BOOLEAN,
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
    """Raised when the FlowSpec lexer encounters an illegal character, invalid indentation, or unterminated string."""

    def __init__(self, message: str, line: int, column: int):
        super().__init__(f"[Line {line}, Col {column}] LexicalError: {message}")
        self.message = message
        self.line = line
        self.column = column


TOKEN_SPECIFICATION = [
    ("COMMENT", r"//[^\n]*|#[^\n]*"),
    ("SKIP", r"[ \r]+"),
    ("OP_LTE", r"<="),
    ("OP_GTE", r">="),
    ("OP_LT", r"<"),
    ("OP_GT", r">"),
    ("OP_PLUS", r"\+"),
    ("OP_MINUS", r"-"),
    ("OP_MUL", r"\*"),
    ("OP_DIV", r"/"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("STRING", r'"(?:\\.|[^"\\])*"'),
    ("NUMBER", r"\d+(?:\.\d+)?"),
    ("IDENTIFIER", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("MISMATCH", r"."),
]

MASTER_REGEX = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPECIFICATION)
)


class FlowSpecLexer:
    """Tokenizes natural indentation-based FlowSpec DSL source code into a stream of Tokens."""

    def tokenize(self, source_code: str) -> List[Token]:
        tokens: List[Token] = []
        indent_stack: List[int] = [0]
        paren_depth = 0
        lines = source_code.splitlines()

        for line_num, raw_line in enumerate(lines, start=1):
            line = raw_line.rstrip("\r")
            stripped = line.lstrip(" ")

            if "\t" in line[: len(line) - len(stripped)]:
                raise FlowSpecLexicalError(
                    "Tabs are not allowed for indentation; use spaces only.",
                    line=line_num,
                    column=1,
                )

            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue

            indent = len(line) - len(stripped)
            if paren_depth == 0:
                if indent > indent_stack[-1]:
                    indent_stack.append(indent)
                    tokens.append(Token(TokenType.INDENT, "", line_num, 1))
                elif indent < indent_stack[-1]:
                    while indent < indent_stack[-1]:
                        indent_stack.pop()
                        tokens.append(Token(TokenType.DEDENT, "", line_num, 1))
                    if indent != indent_stack[-1]:
                        raise FlowSpecLexicalError(
                            f"Inconsistent indentation level ({indent} spaces).",
                            line=line_num,
                            column=1,
                        )

            line_tokens_added = False
            for match in MASTER_REGEX.finditer(line, pos=indent):
                kind = match.lastgroup
                value = match.group()
                column = match.start() + 1

                if kind in ("SKIP", "COMMENT"):
                    continue
                if kind == "MISMATCH":
                    raise FlowSpecLexicalError(
                        f"Unexpected character '{value}'", line=line_num, column=column
                    )

                if kind == "STRING":
                    raw = value[1:-1]
                    unescaped = (
                        raw.replace('\\"', '"')
                        .replace("\\n", "\n")
                        .replace("\\t", "\t")
                        .replace("\\\\", "\\")
                    )
                    tokens.append(Token(TokenType.STRING, unescaped, line_num, column))
                    line_tokens_added = True
                    continue

                if kind == "IDENTIFIER":
                    tok_type = KEYWORDS.get(value, TokenType.IDENTIFIER)
                    tokens.append(Token(tok_type, value, line_num, column))
                    line_tokens_added = True
                    continue

                tok_type = TokenType(kind)
                if tok_type == TokenType.LPAREN:
                    paren_depth += 1
                elif tok_type == TokenType.RPAREN and paren_depth > 0:
                    paren_depth -= 1

                tokens.append(Token(tok_type, value, line_num, column))
                line_tokens_added = True

            if line_tokens_added and paren_depth == 0:
                tokens.append(Token(TokenType.NEWLINE, "", line_num, len(line) + 1))

        end_line = len(lines) + 1
        while len(indent_stack) > 1:
            indent_stack.pop()
            tokens.append(Token(TokenType.DEDENT, "", end_line, 1))

        tokens.append(Token(TokenType.EOF, "", end_line, 1))
        return tokens
