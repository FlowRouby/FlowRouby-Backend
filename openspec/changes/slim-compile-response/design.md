# Design: Optimización del Contrato JSON en Endpoints de Compilación

## Context

Durante la revisión de la respuesta del endpoint `POST /api/v1/processes/compile` se identificó que el payload JSON incluía datos redundantes:
1. Los archivos Ruby generados aparecían dos veces dentro de `generated_ruby` (por categoría y en `files`).
2. El modelo del proceso se serializaba tres veces (`intermediate_model`, `flowspec.ast` y `flowspec.code`).
3. El contrato de datos (`data_contract`) aparecía tanto en la raíz como dentro de `flowspec.semantic_analysis`.

Se acordó limpiar estas tres redundancias y **conservar `formal_analysis.dfa.state_subsets`** ya que aún será objeto de análisis.

## Goals / Non-Goals

**Goals:**
- Reducir el tamaño y la complejidad del JSON devuelto por `POST /api/v1/processes/compile` y `POST /api/v1/flowspec/compile`.
- Retornar en `generated_ruby` únicamente `framework` y el diccionario `files`.
- Retornar `flowspec.code` como la única representación del grafo en el response (removiendo `intermediate_model` y `flowspec.ast` del JSON de salida).
- Mantener `data_contract` únicamente en la raíz del JSON.
- Conservar intacto `formal_analysis.dfa.state_subsets`.

**Non-Goals:**
- No se elimina el uso interno de `ProcessGraph` (`intermediate_model`) ni de `ProcessAST` (`ast`) durante la ejecución del pipeline en memoria; únicamente dejan de volcarse crudos en el JSON HTTP de salida.
- No se modifica el cálculo ni la salida de `formal_analysis`.

## Decisions

### 1. Estructura final del JSON en `POST /api/v1/processes/compile`
```json
{
  "metadata": {
    "process_id": "...",
    "process_name": "...",
    "participant_name": "...",
    "is_executable": true,
    "lanes": ["..."],
    "node_count": 7,
    "edge_count": 6
  },
  "validation": {
    "valid": true,
    "bpmn_warnings": [],
    "semantic_errors": [],
    "semantic_warnings": []
  },
  "data_contract": {
    "required_inputs": [...],
    "produced_outputs": [...],
    "sample_payload": {...}
  },
  "formal_analysis": {
    "chomsky_classification": "Type-3 (Regular Language over Activity Traces)",
    "is_valid_workflow": true,
    "regular_expression": "...",
    "nfa_state_count": 16,
    "dfa": {
      "states": [...],
      "alphabet": [...],
      "start_state": "D0",
      "accept_states": [...],
      "transitions": {...},
      "state_subsets": {...}
    },
    "flag_regions": [...],
    "acyclic_paths": [...],
    "diagnostics": {...}
  },
  "flowspec": {
    "chomsky_classification": "Type-2 (Context-Free Grammar LL(1))",
    "code": "process realizarVisitaTecnica ...",
    "symbol_table": {
      "nodes_count": 7,
      "variables": {...}
    }
  },
  "generated_ruby": {
    "framework": "Ruby on Rails + Sidekiq",
    "files": {
      "app/workflows/realizar_visita_tecnica_workflow.rb": "...",
      "app/forms/activity_1aczp5w_form.rb": "...",
      "app/jobs/activity_0lw92ym_http_job.rb": "...",
      "spec/workflows/realizar_visita_tecnica_workflow_spec.rb": "..."
    }
  }
}
```

## Risks / Trade-offs

- **[Consumidores de tests que leían sub-llaves de `generated_ruby`]** $\rightarrow$ **Mitigación**: Todas las rutas de archivos siguen siendo claramente distinguibles por su prefijo Rails estándar (`app/workflows/`, `app/forms/`, `app/jobs/`, `app/services/`, `spec/workflows/`) dentro de `generated_ruby["files"]`.

