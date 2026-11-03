# Contrato de API: importación BPMN y diagnósticos

Contrato entre el backend (FastAPI) y el frontend (Angular + bpmn-js) para la importación de diagramas BPMN.
Los ejemplos de este documento fueron obtenidos ejecutando la API real; no son ilustrativos.

- Base URL local: `http://localhost:8000` (Swagger en `/docs`).
- Todas las claves de diagnóstico están en `camelCase`. El resto de la respuesta (`metadata`, `formal_analysis`, ...) conserva `snake_case`.
- Los IDs de BPMN (`elementId`) son **los originales del XML**, los mismos que usa bpmn-js. Sirven para resaltar elementos en el canvas.

## 1. Endpoints que reciben BPMN

| Método | Ruta | Entrada | Uso |
|---|---|---|---|
| POST | `/api/v1/processes/compile` | `multipart/form-data`, campo `files` (exactamente 1 archivo `.bpmn` o `.xml`) | Importa, analiza, emite FlowSpec y genera Ruby |
| POST | `/api/v1/processes/simulate` | `multipart/form-data`, campo `file` (`.bpmn`) **o** `flowspec_code`; opcional `input_data` (JSON string) | Simulación sin estado |

Ambos importan el XML con las mismas reglas. No existe todavía un endpoint que **solo importe** (ver sección 6).

## 2. Respuestas

### 2.1 Éxito: `200`
`compile` devuelve, entre otros, estos bloques relacionados con la importación:

```json
{
  "metadata": {
    "process_id": "P",
    "process_name": "Demo",
    "participant_name": null,
    "is_executable": null,
    "lanes": [],
    "node_count": 3,
    "edge_count": 2
  },
  "validation": {
    "valid": true,
    "diagnostics": [],
    "semantic_errors": [],
    "semantic_warnings": []
  }
}
```

- `process_name` cae al `process_id` si el proceso no tiene nombre.
- `is_executable` es `null` cuando el atributo no está en el XML.
- `validation.diagnostics` trae las advertencias e informaciones que **no bloquean** (ver 3). Puede venir vacío.
- Otros bloques de la respuesta (`data_contract`, `formal_analysis`, `flowspec`, `generated_ruby`) no cambian con esta intervención.

### 2.2 El documento no se pudo importar: `422`
Hay errores de estructura. No se construye ningún modelo.

```json
{
  "detail": {
    "message": "The BPMN document could not be imported.",
    "diagnostics": [
      {
        "severity": "error",
        "code": "INVALID_REFERENCE",
        "message": "The sequenceFlow 'f1' references the unknown targetRef 'X'.",
        "elementId": "f1",
        "elementType": "sequenceFlow",
        "processId": "P",
        "blocksAnalysis": false,
        "line": 4
      }
    ]
  }
}
```

`detail.diagnostics` contiene **todos** los errores encontrados, no solo el primero.

### 2.3 Se importó, pero no se puede analizar: `422`
El documento es válido pero contiene algo que FlowRouby todavía no interpreta.

```json
{
  "detail": {
    "message": "The BPMN document was imported but cannot be analyzed yet.",
    "diagnostics": [
      {
        "severity": "warning",
        "code": "UNSUPPORTED_ELEMENT",
        "message": "<subProcess> is not supported yet; it is kept as an opaque node.",
        "elementId": "SP",
        "elementType": "subProcess",
        "processId": "P",
        "blocksAnalysis": true,
        "line": 4
      }
    ]
  }
}
```

Aquí `detail.diagnostics` contiene **solo los diagnósticos que bloquean** (`blocksAnalysis: true`). Las demás advertencias no se incluyen en este caso.

### 2.4 Otros `422` (no son diagnósticos de importación)
Distingue la forma de `detail`:

| Situación | Forma de `detail` |
|---|---|
| Archivo con extensión inválida o más de un archivo | objeto con `message` y `diagnostics` (código `INVALID_UPLOAD`) |
| No se envió el campo `files` | lista de errores de validación de FastAPI: `[{ "type", "loc", "msg", "input" }]` |
| `input_data` no es un JSON objeto (simulate) | `{ "message": "..." }` |
| Error de sintaxis FlowSpec generado | `{ "message", "line", "column", "flowspec_code" }` |

Regla práctica para el frontend: si `detail` es un **array**, es validación de FastAPI; si es un **objeto** con `diagnostics`, es el contrato de este documento.

## 3. Modelo de diagnóstico

| Campo | Tipo | Descripción |
|---|---|---|
| `severity` | `"error"` \| `"warning"` \| `"info"` | Gravedad |
| `code` | string | Código estable (tabla 4) |
| `message` | string | Texto legible en inglés (no usar para lógica) |
| `elementId` | string \| null | ID BPMN original del elemento afectado |
| `elementType` | string \| null | Tag BPMN original (`sequenceFlow`, `subProcess`, ...) |
| `processId` | string \| null | Proceso al que pertenece |
| `blocksAnalysis` | boolean | Si es `true`, el análisis formal no se ejecuta |
| `line` | number \| null | Línea de la etiqueta de apertura del elemento en el XML importado |

Las tres situaciones que distingue el backend:

1. **`error`**: no se puede construir un modelo consistente. HTTP 422.
2. **`warning` / `info` con `blocksAnalysis: false`**: el diagrama se importa y se analiza; el usuario debe estar informado.
3. **`warning` con `blocksAnalysis: true`**: el diagrama se importó, pero el análisis no se ejecuta. HTTP 422 (ver 2.3).

## 4. Códigos

Las reglas marcadas como *perfil FlowRouby* son restricciones explícitas del alcance actual del proyecto, **no** reglas universales de validez de BPMN.

| Código | Severidad | Bloquea | Origen | Significado |
|---|---|---|---|---|
| `INVALID_UPLOAD` | error | n/a | petición | Más de un archivo o extensión distinta de `.bpmn`/`.xml` |
| `XML_MALFORMED` | error | n/a | XML | XML mal formado o con DTD/entidades (rechazado por seguridad) |
| `NOT_BPMN` | error | n/a | BPMN | La raíz no es `definitions` en el namespace BPMN 2.0 |
| `NO_PROCESS` | error | n/a | BPMN | No hay ningún `process` |
| `MISSING_ID` | error | n/a | BPMN | Falta un `id` obligatorio |
| `DUPLICATE_ID` | error | n/a | BPMN | ID repetido (incluye colisión entre nodos y flujos) |
| `MISSING_REF_ATTRIBUTE` | error | n/a | BPMN | `sequenceFlow` sin `sourceRef` o `targetRef` |
| `INVALID_REFERENCE` | error | n/a | BPMN | Referencia a un elemento inexistente (flujo o lane) |
| `NO_START_EVENT` | error | n/a | perfil FlowRouby | El proceso no tiene `startEvent` |
| `NO_END_EVENT` | error | n/a | perfil FlowRouby | El proceso no tiene `endEvent` |
| `UNSUPPORTED_ELEMENT` | warning | **sí** | perfil FlowRouby | Elemento preservado como nodo opaco (subproceso, eventos intermedios, ...) |
| `MULTIPLE_START_EVENTS` | warning | **sí** | perfil FlowRouby | Varios `startEvent`; pendiente de definir su representación formal |
| `MULTIPLE_PROCESSES` | warning | **sí** | perfil FlowRouby | El documento tiene más de un proceso |
| `PRESERVED_NOT_ANALYZABLE` | warning | no | perfil FlowRouby | `callActivity` o `inclusiveGateway`: importados y válidos para generar código, pero fuera del perfil inicial de análisis; los resultados del análisis que los involucren son provisionales |
| `DISCONNECTED_NODE` | warning | no | BPMN | Nodo sin conexiones |
| `GATEWAY_WITHOUT_OUTGOING` | warning | no | BPMN | Compuerta sin flujos de salida |
| `XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT` | warning | no | BPMN | Salida de XOR sin condición y sin ser la default |
| `IGNORED_ELEMENT` | info | no | perfil FlowRouby | Elemento no relevante para el análisis (anotaciones, asociaciones, layout BPMNDI, ...) |

Varios `endEvent` están permitidos y no generan diagnóstico.

## 5. Uso recomendado en el frontend

- Resaltar en el canvas usando `elementId` (ej. `canvas.addMarker(elementId, 'fr-error')`). Puede ser `null`: mostrar entonces solo el mensaje.
- Mostrar `line` como ayuda para localizar el problema en el XML original.
- Decidir la lógica por `code`, `severity` y `blocksAnalysis`; **nunca** por el texto de `message`.
- Tratar `info` como no intrusivo (por ejemplo, un contador), `warning` como aviso visible y `error` como bloqueo.
- `bpmn-js` valida y muestra el diagrama por su cuenta: un `422` del backend no impide visualizar el XML en el canvas.

## 6. Limitaciones y pendientes

1. **No hay endpoint de solo importación.** Hoy un diagrama con `blocksAnalysis: true` devuelve únicamente diagnósticos y no el modelo importado. Se propone `POST /api/v1/processes/import` que devuelva modelo + diagnósticos sin ejecutar análisis. Pendiente de aprobación.
2. **No hay CORS configurado.** El backend no incluye `CORSMiddleware`; el frontend en otro origen será bloqueado por el navegador hasta que se configure.
3. **Sin persistencia.** Nada se guarda; cada petición importa de cero (MongoDB queda para una etapa posterior).
4. `message` está en inglés y no es estable; el frontend debe traducir por `code`.
5. Los endpoints `/api/v1/flowspec/compile` y la simulación sobre `flowspec_code` no forman parte de este contrato.
6. En `compile`, un `process` sin atributo `isExecutable` devuelve `is_executable: null`.
