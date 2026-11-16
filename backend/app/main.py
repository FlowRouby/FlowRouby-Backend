"""FastAPI Entrypoint for the BPMN -> FlowSpec -> Formal Automata -> Ruby on Rails Compiler."""

from __future__ import annotations

import inspect
import os
from typing import Any, Dict
import starlette.routing
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .features.processes.router import router as processes_router

if not hasattr(FastAPI, "max_body_size"):
    FastAPI.max_body_size = None

if "on_startup" not in inspect.signature(starlette.routing.Router.__init__).parameters:
    _orig_router_init = starlette.routing.Router.__init__

    def _compat_router_init(self: Any, *args: Any, on_startup: Any = None, on_shutdown: Any = None, **kwargs: Any) -> None:
        _orig_router_init(self, *args, **kwargs)

    starlette.routing.Router.__init__ = _compat_router_init

app = FastAPI(
    title="SHTLNG BPMN -> FlowSpec -> Ruby Compiler API",
    description=(
        "Compiles BPMN 2.0 / Camunda diagrams into the FlowSpec intermediate DSL, "
        "runs formal verification (ε-NFA, DFA, Regular Expressions), simulates flows statelessly, "
        "and generates Ruby on Rails + Sidekiq templates."
    ),
    version="1.0.0",
)

DEFAULT_CORS_ORIGINS = "http://localhost:4200"
cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(processes_router)


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok", "service": "bpmn-to-ruby-compiler"}
