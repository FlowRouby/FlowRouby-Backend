"""Golden (characterization) test for the generated Ruby project.

Every BPMN file in ``tests/fixtures/ruby_generation`` is compiled through the real
``/api/v1/processes/compile`` endpoint and the generated project (framework string, file
paths and full file contents) is compared with a committed snapshot in
``tests/fixtures/ruby_generation/golden/<fixture>.json``.

The snapshots pin the output of the Ruby generator, so a refactor of the generator must
leave them untouched. To regenerate them after an intentional change of the generated Ruby,
run once with the environment variable ``UPDATE_RUBY_GOLDEN=1``; a default run never writes.
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.main import app

COMPILE_URL = "/api/v1/processes/compile"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ruby_generation"
GOLDEN_DIR = FIXTURES_DIR / "golden"
UPDATE_ENV_VAR = "UPDATE_RUBY_GOLDEN"
FIXTURE_NAMES = sorted(path.stem for path in FIXTURES_DIR.glob("*.bpmn"))

client = TestClient(app)


def _post_fixture(name: str, fmt: str = "json"):
    bpmn = (FIXTURES_DIR / f"{name}.bpmn").read_bytes()
    return client.post(
        COMPILE_URL,
        params={"format": fmt},
        files={"file": (f"{name}.bpmn", bpmn, "application/xml")},
    )


def _generated_ruby(name: str) -> Dict[str, Any]:
    response = _post_fixture(name)
    assert response.status_code == 200, f"{name}: /compile returned {response.status_code}: {response.text[:300]}"
    return response.json()["generated_ruby"]


def _describe_difference(name: str, expected: Dict[str, Any], actual: Dict[str, Any]) -> str:
    lines = [f"Generated Ruby for fixture '{name}' differs from its golden snapshot."]
    if expected["framework"] != actual["framework"]:
        lines.append(f"  framework: {expected['framework']!r} -> {actual['framework']!r}")
    expected_files, actual_files = expected["files"], actual["files"]
    for path in sorted(set(actual_files) - set(expected_files)):
        lines.append(f"  added file: {path}")
    for path in sorted(set(expected_files) - set(actual_files)):
        lines.append(f"  missing file: {path}")
    for path in sorted(set(expected_files) & set(actual_files)):
        if expected_files[path] != actual_files[path]:
            lines.append(f"  changed file: {path}")
    lines.append(f"Set {UPDATE_ENV_VAR}=1 only if the change of generated Ruby is intentional.")
    return "\n".join(lines)


def test_fixtures_are_present():
    assert len(FIXTURE_NAMES) >= 10
    for name in FIXTURE_NAMES:
        assert (GOLDEN_DIR / f"{name}.json").exists() or os.environ.get(UPDATE_ENV_VAR), (
            f"missing golden snapshot for '{name}'; run with {UPDATE_ENV_VAR}=1 to create it"
        )


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_generated_ruby_matches_golden_snapshot(name: str):
    actual = _generated_ruby(name)
    golden_path = GOLDEN_DIR / f"{name}.json"

    if os.environ.get(UPDATE_ENV_VAR):
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(
            json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return

    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    assert actual == expected, _describe_difference(name, expected, actual)


def test_zip_download_contains_the_same_files_as_json():
    name = "rich"
    files = _generated_ruby(name)["files"]
    response = _post_fixture(name, fmt="zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        prefix = names[0].split("/", 1)[0] + "/"
        zipped = {entry[len(prefix):]: archive.read(entry).decode("utf-8") for entry in names}

    assert all(entry.startswith(prefix) for entry in names)
    assert sorted(zipped) == sorted(files)
    assert zipped == files
