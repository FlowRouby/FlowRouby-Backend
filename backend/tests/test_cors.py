"""Tests for the CORS policy that lets the Angular frontend call the API."""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.main import app

FRONTEND_ORIGIN = "http://localhost:4200"
IMPORT_URL = "/api/v1/processes/import"

client = TestClient(app)


def test_preflight_from_the_frontend_origin_is_allowed() -> None:
    response = client.options(
        IMPORT_URL,
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_responses_to_the_frontend_origin_expose_the_download_filename() -> None:
    response = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})

    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "Content-Disposition" in response.headers["access-control-expose-headers"]


def test_other_origins_get_no_cors_headers() -> None:
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
