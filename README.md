# MonteCarlo Lab

Servicio backend en Python para **ejecutar simulaciones de Monte Carlo**, persistir cada corrida en **PostgreSQL** y **procesar datos experimentales** con un pipeline ETL validado. Incluye un **frontend Streamlit** para crear simulaciones, explorar histogramas, trayectorias y series temporales.

Proyecto de portafolio construido para cubrir, de punta a punta, el ciclo de vida de un servicio científico: modelo numérico → API REST → persistencia → ingesta de datos → tests → contenedor → CI → despliegue.

```
56 tests backend + 2 tests de UI · 96% cobertura · ruff limpio · CI con PostgreSQL real
```

> **Demo:** [frontend en Streamlit](https://p776drtvmpekupvxkyiuww.streamlit.app/) · [API en Render](https://montecarlo-lab-api.onrender.com/docs) — desplegada con **Render** (API Docker + PostgreSQL) y **Streamlit Community Cloud**. La guía completa está en [docs/DEPLOY.md](docs/DEPLOY.md).

---

## Qué demuestra

| Responsabilidad | Implementación | Dónde |
|---|---|---|
| Servicios Python para simulaciones Monte Carlo | Motores vectorizados con NumPy: GBM, Ornstein-Uhlenbeck y propagación normal. Reproducibles por semilla | `app/services/montecarlo.py` |
| APIs REST con FastAPI para iniciar y consultar | CRUD de corridas, paginación, validación con Pydantic, OpenAPI automático, manejo de errores de dominio | `app/api/routes/` |
| Persistencia en PostgreSQL | SQLAlchemy 2 tipado, JSONB para parámetros y resumen, tabla de paths con PK compuesta, migraciones Alembic | `app/db/models.py`, `alembic/` |
| ETL de datos experimentales | Validación de esquema, *encoding* y timestamps, deduplicación, outliers por IQR, checksum SHA-256, estadísticas | `app/services/etl.py` |
| Tests unitarios y de integración | 56 tests con `pytest`; los de integración corren contra PostgreSQL migrado con Alembic. 2 tests de UI con `AppTest` | `tests/`, `frontend/tests/` |
| Docker + GitHub Actions | Imagen `slim` no-root con healthcheck, `docker compose` con espera a BD sana, 4 jobs de CI con PostgreSQL, smoke test E2E y AppTest | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` |
| Frontend ligero | Streamlit + Altair: formulario dinámico por modelo, KPIs, histograma, trayectorias, series temporales con outliers, tablas e historial | `frontend/app.py` |
| Despliegue gratuito | `render.yaml` para la API Docker en Render, PostgreSQL gestionado en Render y guía para Streamlit Community Cloud | `render.yaml`, `docs/DEPLOY.md` |

---

## Arquitectura

```
            ┌──────────────────────────────────────────────┐
            │   Streamlit frontend · local / Cloud         │
            │   formulario · KPIs · histograma · series    │
            └──────────────────┬───────────────────────────┘
                               │ HTTP (JSON / multipart)
            ┌──────────────────▼───────────────────────────┐
            │        FastAPI + uvicorn (Docker/Render)     │
            │  /api/v1/simulations    /api/v1/datasets     │
            │  validación Pydantic    health / readiness   │
            └───────┬─────────────────────────┬────────────┘
                    │                         │
     ┌──────────────▼─────────┐   ┌───────────▼─────────────┐
     │  Motor Monte Carlo     │   │   ETL con pandas        │
     │  NumPy vectorizado     │   │  validar → dedupe →     │
     │  GBM / OU / Normal     │   │  outliers → insertar    │
     └──────────────┬─────────┘   └───────────┬─────────────┘
                    │                         │
            ┌───────▼─────────────────────────▼───────────┐
            │          SQLAlchemy 2 + Alembic             │
            │      PostgreSQL 16 (Docker o Render)        │
            └─────────────────────────────────────────────┘
```

El frontend llama a la API **desde el servidor de Streamlit**, no desde el navegador: no necesita CORS ni expone credenciales de base de datos.

---

## Stack

| Pieza | Versión | Uso |
|---|---|---|
| Python | 3.12 | Lenguaje base |
| FastAPI | ≥ 0.115 | API REST, OpenAPI, validación |
| SQLAlchemy | ≥ 2.0 | ORM tipado, consultas y agregaciones SQL |
| Alembic | ≥ 1.13 | Migraciones versionadas |
| PostgreSQL | 16 | Persistencia relacional y JSONB |
| pandas | ≥ 2.2 | ETL y control de calidad de datos |
| NumPy | ≥ 2.0 | Simulación vectorizada |
| Streamlit + Altair | ≥ 1.57 / ≥ 5 | Frontend y gráficos Vega-Lite |
| httpx | ≥ 0.27 | Cliente HTTP del frontend |
| pytest | ≥ 8.2 | Tests unitarios, de integración y de UI |
| Docker / Compose | — | Empaquetado y entorno reproducible |
| GitHub Actions | — | Lint, tests, smoke test y AppTest |
| Render + Render Postgres | Free tier | Despliegue de la API y PostgreSQL gestionado |

---

## Arranque rápido con Docker

Requisitos: Docker con Compose v2.

```bash
docker compose up --build
```

| Servicio | URL |
|---|---|
| Documentación interactiva | http://localhost:8000/docs |
| OpenAPI JSON | http://localhost:8000/openapi.json |
| Health / readiness | http://localhost:8000/health · `/health/ready` |
| Frontend Streamlit | http://localhost:8501 (se arranca aparte, ver abajo) |
| PostgreSQL | Solo en la red de Compose (`db:5432`) |

El contenedor aplica las migraciones de Alembic en el arranque (`docker/entrypoint.sh`) y espera a que la base de datos esté sana. La base no publica puerto en el host para no chocar con un PostgreSQL local; se inspecciona con:

```bash
docker compose exec db psql -U montecarlo -d montecarlo
```

### Frontend local

El frontend es una app Streamlit independiente que consume la API por HTTP:

```bash
pip install -r frontend/requirements.txt
streamlit run frontend/app.py
# http://localhost:8501
```

La URL de la API se edita en la barra lateral (por defecto `http://localhost:8000`). La app comprueba `/health` y `/health/ready` al arrancar y muestra el estado en la barra lateral.

Prueba rápida:

```bash
curl -s http://localhost:8000/api/v1/overview

curl -s -X POST http://localhost:8000/api/v1/simulations \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Proyección Q4",
    "params": {"kind": "gbm", "s0": 100, "mu": 0.07, "sigma": 0.25},
    "n_paths": 2000,
    "n_steps": 252,
    "seed": 42,
    "threshold": 120
  }'

python scripts/smoke_test.py --base-url http://localhost:8000
```

`scripts/smoke_test.py` recorre los tres flujos completos (simulación, ETL y métricas) y devuelve código de salida distinto de cero si algo falla: es el mismo script que ejecuta CI contra el stack dockerizado.

---

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env               # ajusta MC_DATABASE_URL si hace falta
alembic upgrade head
uvicorn app.main:app --reload
```

Base de datos local (una sola vez):

```sql
CREATE ROLE montecarlo LOGIN PASSWORD 'montecarlo' CREATEDB;
CREATE DATABASE montecarlo OWNER montecarlo;
CREATE DATABASE montecarlo_test OWNER montecarlo;   -- solo para tests
```

En PowerShell:

```powershell
$env:MC_DATABASE_URL = "postgresql+psycopg://montecarlo:montecarlo@localhost:5432/montecarlo"
alembic upgrade head
uvicorn app.main:app --reload
```

La configuración se lee de variables `MC_*` o de un `.env` (ver `.env.example`).

---

## API

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/simulations` | Ejecuta y persiste una simulación |
| `GET` | `/api/v1/simulations?status=&limit=&offset=` | Lista corridas con paginación y filtro |
| `GET` | `/api/v1/simulations/{id}` | Detalle de una corrida |
| `GET` | `/api/v1/simulations/{id}/results?sample=200` | Resumen + muestra de valores terminales |
| `GET` | `/api/v1/simulations/{id}/histogram` | Histograma de 24 bins de los valores terminales |
| `GET` | `/api/v1/simulations/{id}/trajectories` | Vista previa acotada de trayectorias (máx. 25 paths × 300 pasos) |
| `GET` | `/api/v1/simulations/{id}/paths?limit=&offset=` | Página los estadísticos por path |
| `DELETE` | `/api/v1/simulations/{id}` | Borra la corrida y sus paths (cascade) |
| `POST` | `/api/v1/datasets` | Sube un CSV (multipart) y ejecuta el ETL |
| `GET` | `/api/v1/datasets` | Lista datasets |
| `GET` | `/api/v1/datasets/{id}` | Detalle y estadísticas almacenadas |
| `GET` | `/api/v1/datasets/{id}/stats` | Estadísticas recalculadas con SQL |
| `GET` | `/api/v1/datasets/{id}/measurements?variable=&only_outliers=` | Consulta mediciones |
| `DELETE` | `/api/v1/datasets/{id}` | Borra dataset y mediciones (cascade) |
| `GET` | `/api/v1/overview` | Métricas agregadas de la plataforma |
| `GET` | `/health`, `/health/ready` | Liveness y readiness (comprueba la BD) |

### Ejemplo de respuesta

```json
{
  "id": "20b2da33-560f-4be5-ae65-b2a085806263",
  "name": "Proyección Q4",
  "model": "gbm",
  "status": "completed",
  "n_paths": 2000,
  "n_steps": 252,
  "seed": 42,
  "duration_ms": 37,
  "summary": {
    "mean": 107.05,
    "std": 27.08,
    "p05": 68.77,
    "p50": 103.71,
    "p95": 156.38,
    "var_95": 68.77,
    "expected_shortfall_95": 63.12,
    "prob_above_threshold": 0.28,
    "histogram": {"bins": ["..."], "counts": ["..."]}
  }
}
```

### Subida de un CSV

```bash
curl -X POST http://localhost:8000/api/v1/datasets \
  -F "file=@data/sample_measurements.csv;type=text/csv" \
  -F "name=May lab run"
```

---

## Modelos matemáticos

**Geometric Brownian Motion** (crecimiento multiplicativo, precios, población):

```
S(t+Δt) = S(t) · exp[(μ − σ²/2)·Δt + σ·√Δt·Z]
```

**Ornstein-Uhlenbeck** (proceso con reversión a la media, ruido correlacionado):

```
X(t+Δt) = X(t)·e^(−θΔt) + μ·(1 − e^(−θΔt)) + σ·√((1 − e^(−2θΔt)) / 2θ)·Z
```

**Normal estático** (propagación de incertidumbre de una medición):

```
X ~ N(μ, σ²)
```

Todas las trayectorias se generan de forma vectorizada (sin bucles sobre paths). Para OU el bucle es sobre pasos temporales con operaciones vectoriales sobre todos los paths a la vez.

**Reproducibilidad:** `numpy.random.default_rng(seed)` garantiza que la misma terna `(params, n_paths, n_steps, seed)` produzca exactamente los mismos valores. Hay un test de integración que crea dos corridas con la misma semilla y compara los valores terminales almacenados.

**Métricas calculadas:** media, desviación típica, mín/máx, percentiles 5/25/50/75/95, VaR al 95 %, *expected shortfall* al 95 %, probabilidad de superar un umbral e histograma de 24 bins.

---

## Pipeline ETL

Al subir un CSV:

1. **Detección de formato**: separador `,`, `;` o tabulador; encoding UTF-8 (con BOM) y fallback a CP1252.
2. **Validación de esquema**: columnas `timestamp` y `value` obligatorias (nombres configurables); `variable` y `unit` opcionales.
3. **Tipado**: timestamps ISO 8601 o segundos Unix; valores numéricos. Las filas que no se pueden convertir se **rechazan y se cuentan**, no se imputan.
4. **Deduplicación** por `(variable, timestamp)`, conservando la última lectura.
5. **Detección de outliers** por regla IQR (1,5 × IQR) **por variable**: se marcan con `is_outlier`, no se eliminan, para no destruir evidencia experimental.
6. **Trazabilidad**: checksum SHA-256 del archivo, número de filas leídas/rechazadas/duplicadas, rango temporal y estadísticas por variable.
7. **Persistencia** por lotes de 5.000 filas dentro de una transacción.

El endpoint `/stats` **recalcula** los agregados con SQL (`avg`, `stddev_samp`, `min`, `max`, `sum(case ...)`) en lugar de confiar ciegamente en el JSON guardado: una comprobación barata de consistencia.

Ejemplo con el dataset sintético incluido (1.443 filas): 1.438 almacenadas, 3 rechazadas (2 valores ausentes + 1 timestamp corrupto), 2 duplicados eliminados y 4 outliers marcados.

---

## Base de datos

```
simulation_runs ──< simulation_paths
datasets        ──< measurements
```

| Tabla | Propósito | Detalles |
|---|---|---|
| `simulation_runs` | Corrida y su resumen | `params`, `summary` y `trajectory_sample` en JSONB, estado, duración, semilla |
| `simulation_paths` | Estadísticos por path | PK compuesta `(run_id, path_index)`, FK con `ON DELETE CASCADE`, índice `(run_id, terminal_value)` |
| `datasets` | CSV ingerido | checksum, contadores de calidad, estadísticas en JSONB |
| `measurements` | Observaciones en formato largo | índice compuesto `(dataset_id, variable, recorded_at)` |

**Por qué los valores terminales van en filas y no en un JSONB:** permiten paginar, indexar y agregar con SQL sin cargar la corrida completa en memoria. El JSONB se reserva para estructuras de forma variable (parámetros y resumen).

**Por qué las trayectorias se guardan acotadas:** el motor calcula todas las rutas en memoria, pero `trajectory_sample` conserva como máximo 25 trayectorias × 300 pasos (~7.500 floats) para que el frontend dibuje el gráfico sin almacenar millones de valores por corrida.

---

## Tests

```bash
# Solo unitarios (no necesitan base de datos)
pytest tests/unit

# Todo (requiere PostgreSQL)
export MC_DATABASE_URL="postgresql+psycopg://montecarlo:montecarlo@localhost:5432/montecarlo_test"
pytest --cov=app --cov-report=term-missing

# UI de Streamlit (no necesita API; usa AppTest)
pytest frontend/tests
```

- **56 tests** de backend y **2 tests** de UI, con **96 %** de cobertura de líneas.
- Unitarios: motores estocásticos (formas, momentos, reproducibilidad), ETL (encoding, delimitadores, outliers, rechazos), validación de payloads.
- Integración: API completa contra PostgreSQL real, con la base migrada por **Alembic** (no `create_all`), para que las migraciones también se testeen.
- Aislamiento: se trunca el esquema antes de cada test.
- **Protección:** el fixture de sesión se niega a ejecutarse si el nombre de la base no termina en `_test`, porque hace `DROP SCHEMA public CASCADE`.

---

## CI/CD

`.github/workflows/ci.yml` define cuatro jobs:

1. **quality** — `ruff check` y `ruff format --check`.
2. **test** — PostgreSQL 16 como *service container*, `pytest` con cobertura y subida de `coverage.xml` como artefacto.
3. **docker** — `docker compose up --build --wait`, `scripts/smoke_test.py` contra el stack real, logs si falla y `down -v` siempre.
4. **frontend** — instala `frontend/requirements.txt` y ejecuta los tests de UI con `AppTest`, sin necesitar la API.

En un repositorio **público** los minutos de GitHub Actions son gratuitos; en uno privado el plan Free incluye 2.000 minutos/mes, de sobra para este pipeline.

---

## Decisiones de diseño

- **Ejecución síncrona con límites explícitos.** Una corrida de 2.000 paths × 252 pasos tarda ~40 ms, así que no tiene sentido introducir una cola. Los límites (`n_paths ≤ 20.000`, `n_steps ≤ 5.000`, `n_paths × n_steps ≤ 2.500.000`) protegen CPU y memoria y devuelven 422 con un mensaje claro. Si el caso de uso creciera, el siguiente paso natural es Celery/ARQ y un estado `queued`.
- **La corrida se persiste antes de calcular.** Si el proceso muere a mitad, queda una fila `running` auditable; si el motor falla, se marca `failed` con el error y un test de integración lo verifica.
- **Semilla explícita.** Sin reproducibilidad no hay auditoría científica posible. `seed` se guarda en la fila.
- **Inserción por lotes.** `execute(insert(...), rows)` con *executemany* en lugar de `add_all`, para no materializar miles de objetos ORM.
- **Outliers marcados, no borrados.** Eliminar un valor extremo puede ocultar exactamente el fenómeno que se investiga.
- **Alembic es la única fuente del esquema.** El contenedor migra al arrancar; los tests migran de cero. No hay `create_all` en producción.
- **Contenedor no-root y healthchecks.** `appuser` (UID 10001), *healthcheck* propio de la imagen y `depends_on: condition: service_healthy` en Compose.
- **Errores de dominio separados de HTTP.** Los servicios lanzan `AppError`; un handler los traduce a JSON con `detail` y `context`.

---

## Estructura

```
.
├── app/
│   ├── api/routes/          # simulations, datasets, overview, health
│   ├── core/                # configuración, errores, logging
│   ├── db/                  # engine, sesión y modelos ORM
│   ├── schemas/             # modelos Pydantic de entrada/salida
│   ├── services/            # motor Monte Carlo, ETL y orquestación
│   └── main.py              # app factory + lifespan
├── alembic/                 # migraciones versionadas
├── tests/
│   ├── unit/
│   └── integration/
├── frontend/                # app Streamlit + tests de UI (AppTest)
│   ├── app.py
│   └── tests/
├── scripts/                 # generador de datos y smoke test
├── data/                    # dataset sintético de ejemplo
├── docs/                    # guía de despliegue Render + Render Postgres
├── docker/entrypoint.sh
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── pyproject.toml
└── .github/workflows/ci.yml
```

---

## Limitaciones y siguientes pasos

- **Autenticación y cuotas por usuario** (API keys o JWT) antes de exponer el servicio.
- **Cola de trabajos** para corridas grandes, con estados `queued`/`running` y notificación.
- **Almacenamiento de objetos** (S3/MinIO) para conservar el CSV original en lugar de solo las mediciones normalizadas.
- **Observabilidad**: métricas Prometheus (`/metrics`), trazas OpenTelemetry y logs estructurados.
- **Paginación por cursor** en `measurements` para datasets de millones de filas.
- **Procesamiento en streaming** para CSV que superen el límite actual de 200.000 filas.

---

## Coste

Todo el stack es software libre y el proyecto se puede desarrollar, testear y publicar **sin pagar nada**:

| Servicio | Opción gratuita |
|---|---|
| Python, FastAPI, SQLAlchemy, pandas, NumPy, pytest | Open source |
| PostgreSQL | Docker local, o free tier de **Render Postgres** / **Neon** / **Supabase** |
| Git + GitHub | Repos públicos y privados gratuitos |
| GitHub Actions | Gratis en repos públicos; 2.000 min/mes en privados (plan Free) |
| Docker Desktop | Gratis para uso personal, educativo y empresas pequeñas* |

\* Alternativas 100 % libres sin licencia: Rancher Desktop, Podman Desktop o Docker Engine en Linux.

Los *free tiers* cambian con el tiempo: conviene revisar límites antes de desplegar. Para el repositorio y la demo, alcanza con ejecutar `docker compose up`.

---

## Licencia

MIT — ver [LICENSE](LICENSE).
