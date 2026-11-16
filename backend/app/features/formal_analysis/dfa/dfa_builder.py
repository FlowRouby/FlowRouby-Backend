"""Deterministic Finite Automaton (DFA) construction via Subset Construction (Powerset Algorithm)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set

from ..nfa.nfa_builder import EPSILON, EpsilonNFA

REASON_UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"
REASON_NO_TRANSITION = "NO_TRANSITION"
REASON_NOT_ACCEPTING_STATE = "NOT_ACCEPTING_STATE"


@dataclass
class DFAWalk:
    """Outcome of running a trace through a DFA, step by step."""

    accepted: bool
    steps: List[Dict[str, Any]] = field(default_factory=list)
    consumed: int = 0
    final_state: str = ""
    rejected_at: Optional[int] = None
    rejection_reason: Optional[str] = None
    expected_symbols: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "steps": [dict(step) for step in self.steps],
            "consumed": self.consumed,
            "final_state": self.final_state,
            "rejected_at": self.rejected_at,
            "rejection_reason": self.rejection_reason,
            "expected_symbols": list(self.expected_symbols),
        }


@dataclass
class DFA:
    """Formal representation of a Deterministic Finite Automaton M = (Q, Σ, δ, q_0, F)."""
    states: List[str] = field(default_factory=list)
    alphabet: List[str] = field(default_factory=list)
    transitions: Dict[str, Dict[str, str]] = field(default_factory=dict)
    start_state: str = "D0"
    accept_states: Set[str] = field(default_factory=set)
    state_subsets: Dict[str, List[str]] = field(default_factory=dict)
    node_to_dfa_states: Dict[str, Set[str]] = field(default_factory=dict)

    def accepts(self, trace: List[str]) -> bool:
        """Simulates a trace of activity IDs in O(n) time."""
        return self.walk(trace).accepted

    def walk(self, trace: List[str]) -> DFAWalk:
        """Runs a trace left to right and reports every step and, if it fails, where and why.

        The first failure wins: the walk stops there and ``steps`` only holds the symbols that
        were consumed. ``final_state`` is the state where the walk stopped (the start state when
        nothing was consumed).
        """
        alphabet = set(self.alphabet)
        curr = self.start_state
        steps: List[Dict[str, Any]] = []
        rejected_at: Optional[int] = None
        reason: Optional[str] = None

        for index, symbol in enumerate(trace):
            if symbol not in alphabet:
                rejected_at, reason = index, REASON_UNKNOWN_SYMBOL
                break
            next_state = self.transitions.get(curr, {}).get(symbol)
            if next_state is None:
                rejected_at, reason = index, REASON_NO_TRANSITION
                break
            steps.append({"index": index, "symbol": symbol, "from_state": curr, "to_state": next_state})
            curr = next_state

        if reason is None and curr not in self.accept_states:
            reason = REASON_NOT_ACCEPTING_STATE

        return DFAWalk(
            accepted=reason is None,
            steps=steps,
            consumed=len(steps),
            final_state=curr,
            rejected_at=rejected_at,
            rejection_reason=reason,
            expected_symbols=sorted(self.transitions.get(curr, {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "states": list(self.states),
            "alphabet": list(self.alphabet),
            "start_state": self.start_state,
            "accept_states": sorted(list(self.accept_states)),
            "transitions": {k: dict(v) for k, v in self.transitions.items()},
            "state_subsets": self.state_subsets,
        }


class DFABuilder:
    """Determinizes an EpsilonNFA into a DFA using the Powerset / Subset Construction algorithm."""

    def build(self, nfa: EpsilonNFA) -> DFA:
        alphabet = sorted(list(nfa.alphabet))
        init_closure = nfa.epsilon_closure({nfa.start_state})

        subset_to_name: Dict[FrozenSet[str], str] = {init_closure: "D0"}
        queue: deque[FrozenSet[str]] = deque([init_closure])

        dfa = DFA(alphabet=alphabet, start_state="D0")

        while queue:
            current_subset = queue.popleft()
            dfa_state_name = subset_to_name[current_subset]
            dfa.states.append(dfa_state_name)
            dfa.transitions.setdefault(dfa_state_name, {})
            dfa.state_subsets[dfa_state_name] = sorted(list(current_subset))

            if any(s in nfa.accept_states for s in current_subset):
                dfa.accept_states.add(dfa_state_name)

            for node_id, nfa_states in nfa.node_to_states.items():
                if current_subset.intersection(nfa_states):
                    dfa.node_to_dfa_states.setdefault(node_id, set()).add(dfa_state_name)

            for symbol in alphabet:
                moved: Set[str] = set()
                for nfa_state in current_subset:
                    targets = nfa.transitions.get(nfa_state, {}).get(symbol, set())
                    moved.update(targets)

                if not moved:
                    continue

                target_closure = nfa.epsilon_closure(moved)
                if target_closure not in subset_to_name:
                    new_name = f"D{len(subset_to_name)}"
                    subset_to_name[target_closure] = new_name
                    queue.append(target_closure)

                dfa.transitions[dfa_state_name][symbol] = subset_to_name[target_closure]

        return dfa

