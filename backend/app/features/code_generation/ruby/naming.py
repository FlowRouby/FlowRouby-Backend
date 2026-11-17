"""Naming for the generated Ruby code.

Turns BPMN/FlowSpec identifiers and display names into valid, readable Ruby file names and
class names, and keeps them unique within one generated project.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Set


def to_snake_case(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+", ascii_text)
    parts: List[str] = []
    for word in words:
        if parts and word[0].isdigit():
            parts[-1] += word.lower()
        else:
            parts.append(word.lower())
    return "_".join(parts) or "step"


def to_pascal_case(text: str) -> str:
    return "".join(part[0].upper() + part[1:] for part in to_snake_case(text).split("_"))


def unique_snake(raw_name: str, fallback_id: str, used: Set[str]) -> str:
    """Snake-case name for ``raw_name`` (or ``fallback_id`` when blank) not yet in ``used``.

    Collisions get a numeric suffix starting at 2. The chosen name is added to ``used``.
    """
    candidate = raw_name.strip() if raw_name and raw_name.strip() else fallback_id
    base = to_snake_case(candidate)
    name = base
    counter = 2
    while name in used:
        name = f"{base}{counter}"
        counter += 1
    used.add(name)
    return name
