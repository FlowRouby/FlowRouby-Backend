"""Regular Expression synthesis (Chomsky Type 3) via State Elimination on a Generalized NFA (GNFA)."""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Set

from ..dfa.dfa_builder import DFA


class RegexSynthesizer:
    """Converts a DFA into an equivalent Regular Expression and enumerates representative paths."""

    def synthesize(self, dfa: DFA) -> str:
        """Uses Kleene / Brzozowski State Elimination to synthesize the regular expression."""
        if not dfa.accept_states:
            return "∅"

        gnfa_start = "__GNFA_START__"
        gnfa_accept = "__GNFA_ACCEPT__"

        states = [gnfa_start] + list(dfa.states) + [gnfa_accept]
        # matrix[u][v] holds the regex label from u to v
        matrix: Dict[str, Dict[str, str]] = {u: {} for u in states}

        matrix[gnfa_start][dfa.start_state] = "ε"
        for acc in dfa.accept_states:
            matrix[acc][gnfa_accept] = "ε"

        for u, trans in dfa.transitions.items():
            for sym, v in trans.items():
                if v in matrix[u]:
                    matrix[u][v] = self._union(matrix[u][v], sym)
                else:
                    matrix[u][v] = sym

        # Eliminate all original DFA states one by one
        for k in list(dfa.states):
            loop_k = matrix[k].pop(k, None)
            star_k = self._star(loop_k) if loop_k else ""

            predecessors = [i for i in states if i != k and k in matrix.get(i, {})]
            successors = [j for j in states if j != k and j in matrix.get(k, {})]

            for i in predecessors:
                r_ik = matrix[i].pop(k)
                for j in successors:
                    r_kj = matrix[k][j]
                    combined = self._concat(self._concat(r_ik, star_k), r_kj)
                    if j in matrix[i]:
                        matrix[i][j] = self._union(matrix[i][j], combined)
                    else:
                        matrix[i][j] = combined

            matrix.pop(k, None)

        return matrix.get(gnfa_start, {}).get(gnfa_accept, "∅")

    def enumerate_acyclic_paths(self, dfa: DFA, max_paths: int = 20) -> List[List[str]]:
        """Enumerates simple acyclic execution traces from start_state to any accept_state."""
        paths: List[List[str]] = []
        queue: deque[tuple[str, List[str], Set[str]]] = deque(
            [(dfa.start_state, [], {dfa.start_state})]
        )

        while queue and len(paths) < max_paths:
            curr_state, trace, visited = queue.popleft()
            if curr_state in dfa.accept_states:
                paths.append(trace)

            for symbol, next_state in dfa.transitions.get(curr_state, {}).items():
                if next_state not in visited:
                    queue.append((next_state, trace + [symbol], visited | {next_state}))

        return paths

    @staticmethod
    def _union(r1: str, r2: str) -> str:
        if not r1:
            return r2
        if not r2 or r1 == r2:
            return r1
        return f"({r1} | {r2})"

    @staticmethod
    def _concat(r1: str, r2: str) -> str:
        if not r1 or r1 == "ε":
            return r2
        if not r2 or r2 == "ε":
            return r1
        return f"{r1} · {r2}"

    @staticmethod
    def _star(r: str) -> str:
        if not r or r == "ε":
            return ""
        if r.startswith("(") and r.endswith(")"):
            return f"{r}*"
        return f"({r})*"

