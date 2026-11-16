"""Tests for the demo BPMN samples endpoints and the repository behind them."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.features.processes.samples.repository import (
    FileSystemSampleProcessRepository,
    SampleProcess,
    default_samples_directory,
)
from app.main import app
from tests.test_bpmn_import import SEQUENTIAL

LIST_URL = "/api/v1/processes/samples"
COMPILE_URL = "/api/v1/processes/compile"
FRONTEND_ORIGIN = "http://localhost:4200"
EXPECTED_IDS = [
    "01-secuencial",
    "02-decision-xor",
    "03-bucle-correccion",
    "04-paralelo-and",
    "05-inclusivo-or",
]

client = TestClient(app)


def test_list_returns_the_five_real_samples_sorted():
    response = client.get(LIST_URL)

    assert response.status_code == 200
    samples = response.json()["samples"]
    assert [s["id"] for s in samples] == EXPECTED_IDS
    for sample in samples:
        assert set(sample) == {"id", "filename", "name", "process_id"}
        assert sample["filename"] == f"{sample['id']}.bpmn"
        assert sample["name"]
        assert sample["process_id"]


def test_fetch_one_returns_xml_that_compiles():
    response = client.get(f"{LIST_URL}/01-secuencial")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert response.headers["content-disposition"] == 'inline; filename="01-secuencial.bpmn"'

    compiled = client.post(COMPILE_URL, files={"file": ("01-secuencial.bpmn", response.content, "application/xml")})
    assert compiled.status_code == 200


def test_unknown_id_is_404_with_message():
    response = client.get(f"{LIST_URL}/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"]["message"]


@pytest.mark.parametrize(
    "sample_id",
    ["..%2F..%2Fbackend%2Fpyproject.toml", "..%2FREADME", "../README", "01-secuencial.bpmn", "%2e%2e%2f%2e%2e%2fREADME"],
)
def test_path_traversal_is_not_found(sample_id):
    response = client.get(f"{LIST_URL}/{sample_id}")

    assert response.status_code == 404
    assert "[project]" not in response.text
    assert "Diagramas" not in response.text


def test_endpoints_replaceable_with_another_repository(monkeypatch):
    from app.features.processes import router as router_module

    class FakeRepository:
        def list(self):
            return [SampleProcess(id="x", filename="x.bpmn", name="X", process_id="P")]

        def get_xml(self, sample_id):
            return "<xml/>" if sample_id == "x" else None

    monkeypatch.setattr(router_module, "sample_repository", FakeRepository())

    assert client.get(LIST_URL).json() == {
        "samples": [{"id": "x", "filename": "x.bpmn", "name": "X", "process_id": "P"}]
    }
    assert client.get(f"{LIST_URL}/x").text == "<xml/>"
    assert client.get(f"{LIST_URL}/y").status_code == 404


def test_paths_are_documented_in_openapi():
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/processes/samples" in paths
    assert "/api/v1/processes/samples/{sample_id}" in paths


def test_cors_allows_the_frontend_origin():
    preflight = client.options(
        LIST_URL,
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == FRONTEND_ORIGIN

    response = client.get(LIST_URL, headers={"Origin": FRONTEND_ORIGIN})
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


# --- repository unit tests -------------------------------------------------


def test_repository_empty_directory(tmp_path: Path):
    repo = FileSystemSampleProcessRepository(tmp_path)

    assert repo.list() == []
    assert repo.get_xml("anything") is None


def test_repository_missing_directory(tmp_path: Path):
    repo = FileSystemSampleProcessRepository(tmp_path / "nope")

    assert repo.list() == []
    assert repo.get_xml("anything") is None


def test_repository_skips_non_importable_and_non_bpmn_files(tmp_path: Path):
    (tmp_path / "b-good.bpmn").write_text(SEQUENTIAL, encoding="utf-8")
    (tmp_path / "a-good.bpmn").write_text(SEQUENTIAL, encoding="utf-8")
    (tmp_path / "broken.bpmn").write_text("<not xml", encoding="utf-8")
    (tmp_path / "README.md").write_text("# notes", encoding="utf-8")

    repo = FileSystemSampleProcessRepository(tmp_path)

    assert [s.id for s in repo.list()] == ["a-good", "b-good"]
    assert repo.list()[0].filename == "a-good.bpmn"
    assert repo.get_xml("broken") is None
    assert repo.get_xml("README") is None
    assert repo.get_xml("a-good") == SEQUENTIAL


def test_repository_rejects_traversal_ids(tmp_path: Path):
    (tmp_path / "ok.bpmn").write_text(SEQUENTIAL, encoding="utf-8")
    (tmp_path.parent / "secret.bpmn").write_text(SEQUENTIAL, encoding="utf-8")
    repo = FileSystemSampleProcessRepository(tmp_path)

    assert repo.get_xml("../secret") is None
    assert repo.get_xml("ok/../ok") is None


def test_default_directory_points_to_repo_samples():
    assert default_samples_directory().name == "bpmn"
    assert (default_samples_directory() / "README.md").is_file()


def test_samples_dir_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SAMPLES_DIR", str(tmp_path))

    assert default_samples_directory() == tmp_path
