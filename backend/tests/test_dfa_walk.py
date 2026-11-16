"""Tests for DFA.walk(): the step-by-step membership check behind DFA.accepts()."""

from __future__ import annotations

import itertools
import os
import sys
from typing import Dict, List, Set

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.features.formal_analysis.dfa.dfa_builder import DFA


def make_dfa(
    transitions: Dict[str, Dict[str, str]],
    accept_states: Set[str],
    alphabet: List[str],
    start_state: str = "D0",
) -> DFA:
    states = sorted(set(transitions) | {t for row in transitions.values() for t in row.values()} | {start_state})
    return DFA(
        states=states,
        alphabet=sorted(alphabet),
        transitions={state: dict(transitions.get(state, {})) for state in states},
        start_state=start_state,
        accept_states=set(accept_states),
    )


def sequential_dfa() -> DFA:
    """start_1 -> task_1 -> end_1."""
    return make_dfa(
        {"D0": {"start_1": "D1"}, "D1": {"task_1": "D2"}, "D2": {"end_1": "D3"}},
        {"D3"},
        ["start_1", "task_1", "end_1"],
    )


def choice_dfa() -> DFA:
    """start_1 then either task_1 or task_2, then the matching end event."""
    return make_dfa(
        {
            "D0": {"start_1": "D1"},
            "D1": {"task_1": "D2", "task_2": "D3"},
            "D2": {"end_1": "D4"},
            "D3": {"end_2": "D4"},
        },
        {"D4"},
        ["start_1", "task_1", "task_2", "end_1", "end_2"],
    )


def loop_dfa() -> DFA:
    """start_1 then task_1 repeated one or more times, then end_1."""
    return make_dfa(
        {"D0": {"start_1": "D1"}, "D1": {"task_1": "D2"}, "D2": {"task_1": "D2", "end_1": "D3"}},
        {"D3"},
        ["start_1", "task_1", "end_1"],
    )


def accepting_start_dfa() -> DFA:
    """The start state is accepting, so the empty trace belongs to the language."""
    return make_dfa({"D0": {"a": "D1"}, "D1": {"a": "D0"}}, {"D0"}, ["a"])


def old_accepts(dfa: DFA, trace: List[str]) -> bool:
    """Reference copy of the original DFA.accepts() loop, kept to prove the refactor is equivalent."""
    curr = dfa.start_state
    for symbol in trace:
        next_state = dfa.transitions.get(curr, {}).get(symbol)
        if next_state is None:
            return False
        curr = next_state
    return curr in dfa.accept_states


def test_accepted_trace_lists_every_step_and_ends_in_an_accepting_state() -> None:
    walk = sequential_dfa().walk(["start_1", "task_1", "end_1"])

    assert walk.accepted is True
    assert walk.consumed == 3
    assert walk.final_state == "D3"
    assert walk.rejected_at is None and walk.rejection_reason is None
    assert walk.steps == [
        {"index": 0, "symbol": "start_1", "from_state": "D0", "to_state": "D1"},
        {"index": 1, "symbol": "task_1", "from_state": "D1", "to_state": "D2"},
        {"index": 2, "symbol": "end_1", "from_state": "D2", "to_state": "D3"},
    ]
    assert walk.expected_symbols == []


def test_unknown_symbol_stops_the_walk_at_that_position() -> None:
    walk = sequential_dfa().walk(["start_1", "ghost", "end_1"])

    assert walk.accepted is False
    assert (walk.rejection_reason, walk.rejected_at, walk.consumed) == ("UNKNOWN_SYMBOL", 1, 1)
    assert walk.final_state == "D1"
    assert [step["symbol"] for step in walk.steps] == ["start_1"]
    assert walk.expected_symbols == ["task_1"]


def test_symbol_in_the_alphabet_without_a_transition_is_no_transition() -> None:
    walk = sequential_dfa().walk(["start_1", "end_1"])

    assert (walk.accepted, walk.rejection_reason, walk.rejected_at, walk.consumed) == (False, "NO_TRANSITION", 1, 1)
    assert walk.final_state == "D1"
    assert walk.expected_symbols == ["task_1"]


def test_consumed_trace_in_a_non_accepting_state_is_not_accepting_state() -> None:
    walk = sequential_dfa().walk(["start_1", "task_1"])

    assert (walk.accepted, walk.rejection_reason, walk.rejected_at, walk.consumed) == (False, "NOT_ACCEPTING_STATE", None, 2)
    assert walk.final_state == "D2"
    assert walk.expected_symbols == ["end_1"]


def test_empty_trace_is_rejected_from_the_start_state_unless_it_is_accepting() -> None:
    rejected = sequential_dfa().walk([])
    assert (rejected.accepted, rejected.rejection_reason, rejected.rejected_at, rejected.consumed) == (
        False,
        "NOT_ACCEPTING_STATE",
        None,
        0,
    )
    assert rejected.final_state == "D0" and rejected.steps == [] and rejected.expected_symbols == ["start_1"]

    accepted = accepting_start_dfa().walk([])
    assert (accepted.accepted, accepted.rejection_reason, accepted.final_state) == (True, None, "D0")


def test_first_failure_wins_when_a_later_symbol_would_also_fail() -> None:
    walk = sequential_dfa().walk(["end_1", "ghost"])

    assert (walk.rejection_reason, walk.rejected_at, walk.consumed) == ("NO_TRANSITION", 0, 0)
    assert walk.final_state == "D0"


def test_expected_symbols_are_sorted_and_may_be_empty() -> None:
    walk = choice_dfa().walk(["start_1", "end_2"])
    assert walk.expected_symbols == ["task_1", "task_2"]

    done = choice_dfa().walk(["start_1", "task_1", "end_1", "end_1"])
    assert (done.rejection_reason, done.rejected_at, done.final_state) == ("NO_TRANSITION", 3, "D4")
    assert done.expected_symbols == []


def test_to_dict_exposes_every_field() -> None:
    payload = sequential_dfa().walk(["start_1", "ghost"]).to_dict()

    assert set(payload) == {
        "accepted",
        "steps",
        "consumed",
        "final_state",
        "rejected_at",
        "rejection_reason",
        "expected_symbols",
    }
    assert payload["steps"] == [{"index": 0, "symbol": "start_1", "from_state": "D0", "to_state": "D1"}]


def test_accepts_delegates_to_walk() -> None:
    dfa = loop_dfa()
    assert dfa.accepts(["start_1", "task_1", "task_1", "end_1"]) is True
    assert dfa.accepts(["start_1", "end_1"]) is False
    assert dfa.accepts([]) is False


def test_accepts_matches_the_previous_algorithm_over_many_traces() -> None:
    dfas = [sequential_dfa(), choice_dfa(), loop_dfa(), accepting_start_dfa()]
    extra = ["ghost"]

    checked = 0
    for dfa in dfas:
        symbols = list(dfa.alphabet) + extra
        for length in range(0, 6):
            for trace in itertools.product(symbols, repeat=length):
                expected = old_accepts(dfa, list(trace))
                assert dfa.accepts(list(trace)) is expected, (dfa.alphabet, trace)
                assert dfa.walk(list(trace)).accepted is expected, (dfa.alphabet, trace)
                checked += 1
    assert checked > 1000
