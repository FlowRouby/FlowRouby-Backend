"""API documentation for the generated Rails project.

Produces an OpenAPI description of the two generated endpoints and a static page that renders it
with Swagger UI. The request body of the execute endpoint is built from the process variables, so
the documentation always matches the compiled diagram.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ...flowspec.ast.nodes import ProcessAST

SWAGGER_UI_VERSION = "5.17.14"

SWAGGER_UI_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} - API docs</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@{version}/swagger-ui.css">
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@{version}/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({{ url: "/openapi.json", dom_id: "#swagger-ui" }});
    </script>
  </body>
</html>
"""


def build_api_docs(ast: ProcessAST, proc_snake: str, sample_payload: Dict[str, Any]) -> Dict[str, str]:
    """Returns the OpenAPI file and the Swagger UI page, keyed by their path in the project."""
    process_name = ast.name or ast.process_id
    spec = _build_openapi(ast.process_id, process_name, proc_snake, sample_payload)
    return {
        "public/openapi.json": json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        "public/docs/index.html": SWAGGER_UI_PAGE_TEMPLATE.format(title=process_name, version=SWAGGER_UI_VERSION),
    }


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _build_openapi(
    process_id: str, process_name: str, proc_snake: str, sample_payload: Dict[str, Any]
) -> Dict[str, Any]:
    variables = {name: {"type": _json_type(value)} for name, value in sample_payload.items()}
    return {
        "openapi": "3.0.3",
        "info": {
            "title": f"{process_name} workflow API",
            "version": "1.0.0",
            "description": f"Endpoints generated from the BPMN process `{process_id}`.",
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Check that the service is running",
                    "responses": {
                        "200": {
                            "description": "The service is up",
                            "content": {
                                "application/json": {"example": {"status": "ok", "workflow": process_id}}
                            },
                        }
                    },
                }
            },
            f"/workflows/{proc_snake}/execute": {
                "post": {
                    "summary": "Run the workflow from start to end with the given process variables",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "payload": {
                                            "type": "object",
                                            "description": "Process variables read by forms, conditions and tasks.",
                                            "properties": variables,
                                        }
                                    },
                                },
                                "example": {"payload": sample_payload},
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "The workflow ran",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "completed": {"type": "boolean"},
                                            "status": {"type": "string"},
                                            "visited_nodes": {"type": "array", "items": {"type": "string"}},
                                            "enqueued_jobs": {"type": "array", "items": {"type": "object"}},
                                            "context": {"type": "object"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }
