# Asistente de desempeño de campañas

Copiloto interno para un empleado del banco: consulta métricas de campañas de marketing (ROI, conversiones, costo, cobertura) sobre Gold mensual y responde en español o portugués.

El modelo **no escribe SQL**. Llena un formulario Pydantic; DuckDB consulta `data/gold/campaign_channel_performance.parquet`. El rol sale de la sesión de prueba, no del texto del chat.

## Qué incluye

- Chat (ES/PT) por WebSocket + Celery
- Una herramienta: `consultar_desempeno_campanas`
- Roles: **analyst** (métricas completas, límite 50) y **viewer** (ROI, cobertura, conversiones reales; límite 10)
- HITL si `cobertura_minima < 70`
- Hilo por navegador (`visitor_id` en `localStorage`), no un historial global por rol
- Pipeline medallón en el host (bronze → silver → gold / atribución last-touch)

## Arquitectura

```
Navegador  →  FastAPI :8000 (estáticos + /ws/{sesion}?vid=…)
                 │
                 ├─ Redis (broker Celery, pub/sub, checkpointer LangGraph)
                 └─ Worker Celery  →  Deep Agents (GPT-4o) + DuckDB/Gold
```

La imagen Docker **no** copia `pipeline/` ni el parquet: Gold se monta en `./data/gold` (solo lectura).

## Requisitos

- Docker Compose
- `data/gold/campaign_channel_performance.parquet` (generado por el pipeline o copiado a esa ruta)
- Archivo `.env` en la raíz (no se versiona):

```
OPENAI_API_KEY=…
REDIS_HOST=redis
REDIS_PORT=6379
```

En Compose, `REDIS_HOST=redis` lo pisa el `docker-compose.yml`. Fuera de Docker usa `localhost`.

## Arranque

Desde la raíz del repo:

```bash
docker compose up --build
```

UI: [http://localhost:8000](http://localhost:8000)

Tras cambiar `frontend/`, `app/`, `tools/`, `config.py` o `worker/`, hay que **rebuild** (el código va en la imagen; Gold es el único bind mount).

## Sesiones de prueba

| Sesión   | Rol                 | Datos |
|----------|---------------------|--------|
| analyst  | `marketing_analyst` | Todas las métricas del tool |
| viewer   | `marketing_viewer`  | Sin costo ni valor creditado |

El idioma de la UI es el botón ES/PT. El del agente sigue el último mensaje del usuario.

## Pipeline (en el host, no en el contenedor)

Con el entorno Python del proyecto y datos en `data/raw`:

```bash
python pipeline/bronze.py
python pipeline/silver.py
python pipeline/gold.py
python pipeline/gold_attribution.py
```

`gold_attribution.py` escribe el parquet que consume el agente (atribución **last-touch**; no imputa `send_cost` faltante).

## Tests

```bash
python -m pytest tests/test_auth.py tests/test_tools.py -q
```

`tests/test_middleware.py` publica progreso a Redis; hace falta un Redis alcanzable con el `REDIS_HOST` del `.env`.

## Arquitectura completa

Hay dos caminos que no se mezclan en runtime: **el lake (host)** y **el asistente (Compose)**.

```
data/raw/*.csv
        │
        ▼
pipeline/bronze.py  →  data/bronze/   (contratos Pandera, cuarentena)
pipeline/silver.py  →  data/silver/   (tipos, FX, limpiezas)
pipeline/gold.py    →  data/gold/     (tabla de entrenamiento / features)
pipeline/gold_attribution.py
        │
        ▼
data/gold/campaign_channel_performance.parquet
        │  (volumen Docker :ro)
        ▼
┌─────────────────────────────────────────────────────────────┐
│  web (FastAPI)           frontend/  estáticos ES/PT         │
│    app/auth.py           sesiones analyst | viewer          │
│    app/main.py           WS /ws/{sesion}?vid=               │
│                          listener Redis canal:{thread_id}   │
└──────────────┬──────────────────────────────────────────────┘
               │  Celery .delay()
               ▼
┌─────────────────────────────────────────────────────────────┐
│  worker                                                  │
│    Deep Agents + GPT-4o                                  │
│    system prompt + skills/data_analyst                   │
│    middleware: fallback, resumen, auth de tools,         │
│                retry, sanitizar salida                   │
│    tools/queries.py  →  DuckDB + parquet Gold            │
│    interrupt_on cobertura_minima < 70                    │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
Redis Stack
  · cola Celery
  · pub/sub  canal:{thread_id}
  · RedisSaver (historial LangGraph por thread_id)
```

`thread_id` = `{user_id}:{visitor_id}`. El rol (`marketing_analyst` / `marketing_viewer`) viaja en `configurable`; el modelo no lo elige.

## Qué pasa en una petición

Camino feliz (cobertura ≥ 70, sin HITL):

1. El navegador abre `/ws/analyst?vid=<uuid>` (o `viewer`). FastAPI resuelve la sesión de prueba y arma el `thread_id`.
2. El front se suscribe de hecho al canal Redis de ese hilo (el servidor lo hace al conectar el WS).
3. El usuario envía texto. El front pinta la burbuja local y un estado temporal “Consultando…”.
4. FastAPI **no** llama al LLM: encola `ejecutar_agente.delay(thread_id, user_id, role, message)`.
5. El worker publica `{tipo: "progreso", paso_key: "thinking"}` y hace `agent.invoke` con `HumanMessage` y el checkpointer Redis.
6. El modelo decide filtros del formulario. Antes de ejecutar el tool, el middleware recorta métricas/límite según el rol y deniega tools prohibidas.
7. `query_campaign_performance` traduce el formulario a SQL ligado (`?`) y lee el parquet. El tool devuelve registros JSON (hechos), no una tabla markdown.
8. Si el tool corre, el middleware publica progreso (`consultar_desempeno_campanas`). El modelo narra el hallazgo.
9. El worker publica `{status: "completed", response_text: …}` en `canal:{thread_id}`.
10. El listener del WS lo reenvía al navegador. El front borra el paso temporal y muestra el relato.

Si el modelo pide `cobertura_minima < 70`:

11. LangGraph **interrumpe antes** de ejecutar el tool. El worker publica `awaiting_approval` (no hay tabla todavía).
12. El front muestra Aprobar / Rechazar. Al pulsar, manda `{type: "hitl_decision", decision: "approve"|"reject"}`.
13. FastAPI encola `reanudar_agente` con `Command(resume=…)`. Tras aprobar, el wrap de la tool sí corre (consulta Gold) y el flujo vuelve al paso 8–10.

Keepalive: el front envía `__ping__`; el servidor responde `__pong__`. Eso no entra al agente.


