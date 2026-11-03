<div align="center">

# MonteCarlo Lab

**Stochastische Simulationen als vollständiger wissenschaftlicher Dienst.**

Vom numerischen Modell über die REST-API und PostgreSQL bis zum interaktiven Dashboard –
reproduzierbar, validiert, getestet und deploybar.

<br />

[![Live-Demo](https://img.shields.io/badge/Live--Demo-Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://p776drtvmpekupvxkyiuww.streamlit.app/)
[![API](https://img.shields.io/badge/API-OpenAPI--Doku-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://montecarlo-lab-api.onrender.com/docs)
[![Deployment](https://img.shields.io/badge/Deployment-Anleitung-1F2328?style=for-the-badge&logo=render&logoColor=white)](docs/DEPLOY.md)

<br />

[![CI](https://img.shields.io/github/actions/workflow/status/dgoo24/montecarlo-lab/ci.yml?branch=main&label=CI&logo=githubactions&logoColor=white&style=flat-square)](https://github.com/dgoo24/montecarlo-lab/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white&style=flat-square)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white&style=flat-square)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white&style=flat-square)](https://www.postgresql.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.57%2B-FF4B4B?logo=streamlit&logoColor=white&style=flat-square)](https://streamlit.io/)
[![Tests](https://img.shields.io/badge/Tests-58%20bestanden-2EA043?logo=pytest&logoColor=white&style=flat-square)](tests/)
[![Coverage](https://img.shields.io/badge/Coverage-96%25-2EA043?style=flat-square)](tests/)
[![Lint](https://img.shields.io/badge/Lint-Ruff%20clean-D7FF64?style=flat-square&logoColor=black)](pyproject.toml)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white&style=flat-square)](docker-compose.yml)
[![Lizenz](https://img.shields.io/badge/Lizenz-MIT-3DA639?style=flat-square)](LICENSE)

</div>

<br />

> **Kurzfassung.** Dieses Portfolio-Projekt deckt den gesamten Lebenszyklus eines wissenschaftlichen Dienstes ab:
> **numerisches Modell → REST-API → Persistenz → Datenaufnahme → Tests → Container → CI → Deployment.**
> Jeder Lauf ist über einen expliziten Seed reproduzierbar, jede Migration versioniert, jeder Endpoint dokumentiert.

---

## Schnellstart

```bash
git clone https://github.com/dgoo24/montecarlo-lab.git
cd montecarlo-lab
docker compose up --build
```

| Dienst | URL |
|---|---|
| Interaktive API-Dokumentation | <http://localhost:8000/docs> |
| OpenAPI-Spezifikation | <http://localhost:8000/openapi.json> |
| Health / Readiness | <http://localhost:8000/health> · <http://localhost:8000/health/ready> |
| Streamlit-Frontend | <http://localhost:8501> (separat starten, siehe unten) |
| PostgreSQL | nur im Compose-Netz (`db:5432`) |

Der Container führt beim Start die Alembic-Migrationen aus (`docker/entrypoint.sh`) und wartet, bis die
Datenbank gesund ist. Die Datenbank veröffentlicht keinen Port auf dem Host, um Konflikte mit einem lokalen
PostgreSQL zu vermeiden; inspizieren lässt sie sich mit:

```bash
docker compose exec db psql -U montecarlo -d montecarlo
```

> [!TIP]
> Die gehostete API läuft im **Render Free Tier** und schläft nach Inaktivität ein. Der erste Request kann
> daher bis zu ~50 Sekunden dauern – danach antwortet sie in Millisekunden.

---

## Auf einen Blick

| | |
|---|---|
| **Engine** | Vektorisierte Monte-Carlo-Simulationen mit NumPy: GBM, Ornstein-Uhlenbeck, Normalverteilung |
| **API** | FastAPI mit Pydantic-Validierung, Paginierung, OpenAPI und Domänenfehlerbehandlung |
| **Daten** | PostgreSQL 16, typisiertes SQLAlchemy 2, JSONB für variable Strukturen, Alembic-Migrationen |
| **Datenaufnahme** | ETL mit pandas: Encoding-, Schema- und Zeitstempelprüfung, Dedupe, IQR-Ausreißer, SHA-256 |
| **Frontend** | Streamlit + Altair: modellabhängiges Formular, KPIs, Histogramm, Pfade, Zeitreihen |
| **Qualität** | 58 Tests (56 Backend + 2 UI), 96 % Abdeckung, Ruff ohne Befunde, CI mit echtem PostgreSQL |
| **Betrieb** | Schlankes Non-Root-Docker-Image, Healthchecks, 4 CI-Jobs, kostenloses Deployment |

---

## Inhalt

| Abschnitt | Abschnitt |
|---|---|
| [Architektur](#architektur) | [API](#api) |
| [Technologie-Stack](#technologie-stack) | [Mathematische Modelle](#mathematische-modelle) |
| [Lokale Entwicklung](#lokale-entwicklung) | [ETL-Pipeline](#etl-pipeline) |
| [Frontend](#frontend) | [Datenbank](#datenbank) |
| [Was das Projekt zeigt](#was-das-projekt-zeigt) | [Tests](#tests) |
| [CI/CD](#cicd) | [Designentscheidungen](#designentscheidungen) |
| [Projektstruktur](#projektstruktur) | [Grenzen und nächste Schritte](#grenzen-und-nächste-schritte) |

---

## Architektur

```mermaid
flowchart TB
    UI["<b>Streamlit-Frontend</b><br/>Formular · KPIs · Histogramm · Zeitreihen"]

    subgraph API_SVC["FastAPI + uvicorn · Docker / Render"]
        API["REST-API <code>/api/v1</code><br/>Pydantic · OpenAPI · Healthchecks"]
        MC["<b>Monte-Carlo-Engine</b><br/>NumPy vektorisiert · GBM / OU / Normal"]
        ETL["<b>ETL mit pandas</b><br/>validieren → dedupe → Ausreißer → einfügen"]
    end

    DB[("<b>PostgreSQL 16</b><br/>SQLAlchemy 2 + Alembic")]

    UI -->|"HTTP / JSON · multipart"| API
    API --> MC
    API --> ETL
    MC --> DB
    ETL --> DB
```

Das Frontend ruft die API **vom Streamlit-Server** auf, nicht aus dem Browser: Es benötigt kein CORS und
gibt keine Datenbank-Zugangsdaten preis.

---

## Was das Projekt zeigt

| Aufgabe | Umsetzung | Ort |
|---|---|---|
| Python-Dienste für Monte-Carlo-Simulationen | Vektorisierte Engines mit NumPy: GBM, Ornstein-Uhlenbeck und normale Unsicherheitsfortpflanzung. Reproduzierbar über den Seed | `app/services/montecarlo.py` |
| REST-APIs mit FastAPI zum Starten und Abfragen | CRUD für Läufe, Paginierung, Validierung mit Pydantic, automatisches OpenAPI, Domänenfehlerbehandlung | `app/api/routes/` |
| Persistenz in PostgreSQL | Typisiertes SQLAlchemy 2, JSONB für Parameter und Zusammenfassung, Pfadtabelle mit zusammengesetztem Primärschlüssel, Alembic-Migrationen | `app/db/models.py`, `alembic/` |
| ETL experimenteller Daten | Schema-, Encoding- und Zeitstempelvalidierung, Deduplizierung, IQR-Ausreißer, SHA-256-Prüfsumme, Statistiken | `app/services/etl.py` |
| Unit- und Integrationstests | 56 Tests mit `pytest`; Integrationstests laufen gegen ein mit Alembic migriertes PostgreSQL. 2 UI-Tests mit `AppTest` | `tests/`, `frontend/tests/` |
| Docker + GitHub Actions | Schlankes Non-Root-Image mit Healthcheck, `docker compose` mit Warten auf gesunde Datenbank, 4 CI-Jobs mit PostgreSQL, E2E-Smoke-Test und AppTest | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` |
| Leichtes Frontend | Streamlit + Altair: modellabhängiges Formular, KPIs, Histogramm, Pfade, Zeitreihen mit Ausreißern, Tabellen und Verlauf | `frontend/app.py` |
| Kostenloses Deployment | `render.yaml` für die Docker-API auf Render, verwaltetes PostgreSQL auf Render und Anleitung für Streamlit Community Cloud | `render.yaml`, `docs/DEPLOY.md` |

---

## Technologie-Stack

| Komponente | Version | Verwendung |
|---|---|---|
| Python | 3.12 | Basissprache |
| FastAPI | ≥ 0.115 | REST-API, OpenAPI, Validierung |
| SQLAlchemy | ≥ 2.0 | Typisiertes ORM, Abfragen und SQL-Aggregationen |
| Alembic | ≥ 1.13 | Versionierte Migrationen |
| PostgreSQL | 16 | Relationale Persistenz und JSONB |
| pandas | ≥ 2.2 | ETL und Datenqualitätskontrolle |
| NumPy | ≥ 2.0 | Vektorisierte Simulation |
| Streamlit + Altair | ≥ 1.57 / ≥ 5 | Frontend und Vega-Lite-Diagramme |
| httpx | ≥ 0.27 | HTTP-Client des Frontends |
| pytest | ≥ 8.2 | Unit-, Integrations- und UI-Tests |
| Docker / Compose | — | Paketierung und reproduzierbare Umgebung |
| GitHub Actions | — | Lint, Tests, Smoke-Test und AppTest |
| Render + Render Postgres | Free-Tier | Deployment der API und verwaltetes PostgreSQL |

---

## Frontend

Das Frontend ist eine eigenständige Streamlit-App, die die API über HTTP nutzt:

```bash
pip install -r frontend/requirements.txt
streamlit run frontend/app.py
# http://localhost:8501
```

Die API-URL wird in der Seitenleiste bearbeitet (Standard: `http://localhost:8000`). Die App prüft beim Start
`/health` und `/health/ready` und zeigt den Status in der Seitenleiste an.

---

## Lokale Entwicklung

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env               # MC_DATABASE_URL bei Bedarf anpassen
alembic upgrade head
uvicorn app.main:app --reload
```

Lokale Datenbank (einmalig):

```sql
CREATE ROLE montecarlo LOGIN PASSWORD 'montecarlo' CREATEDB;
CREATE DATABASE montecarlo OWNER montecarlo;
CREATE DATABASE montecarlo_test OWNER montecarlo;   -- nur für Tests
```

<details>
<summary><b>Windows / PowerShell</b></summary>

```powershell
$env:MC_DATABASE_URL = "postgresql+psycopg://montecarlo:montecarlo@localhost:5432/montecarlo"
alembic upgrade head
uvicorn app.main:app --reload
```

</details>

Die Konfiguration wird aus `MC_*`-Umgebungsvariablen oder einer `.env`-Datei gelesen (siehe `.env.example`).

---

## API

| Methode | Route | Beschreibung |
|---|---|---|
| `POST` | `/api/v1/simulations` | Führt eine Simulation aus und persistiert sie |
| `GET` | `/api/v1/simulations?status=&limit=&offset=` | Listet Läufe mit Paginierung und Filter |
| `GET` | `/api/v1/simulations/{id}` | Details eines Laufs |
| `GET` | `/api/v1/simulations/{id}/results?sample=200` | Zusammenfassung + Stichprobe der Endwerte |
| `GET` | `/api/v1/simulations/{id}/histogram` | Histogramm mit 24 Bins der Endwerte |
| `GET` | `/api/v1/simulations/{id}/trajectories` | Begrenzte Vorschau der Pfade (max. 25 Pfade × 300 Schritte) |
| `GET` | `/api/v1/simulations/{id}/paths?limit=&offset=` | Paginiert die Statistiken pro Pfad |
| `DELETE` | `/api/v1/simulations/{id}` | Löscht den Lauf und seine Pfade (Cascade) |
| `POST` | `/api/v1/datasets` | Lädt eine CSV hoch (Multipart) und führt die ETL aus |
| `GET` | `/api/v1/datasets` | Listet Datensätze |
| `GET` | `/api/v1/datasets/{id}` | Details und gespeicherte Statistiken |
| `GET` | `/api/v1/datasets/{id}/stats` | Mit SQL neu berechnete Statistiken |
| `GET` | `/api/v1/datasets/{id}/measurements?variable=&only_outliers=` | Fragt Messungen ab |
| `DELETE` | `/api/v1/datasets/{id}` | Löscht Datensatz und Messungen (Cascade) |
| `GET` | `/api/v1/overview` | Aggregierte Plattformmetriken |
| `GET` | `/health`, `/health/ready` | Liveness und Readiness (prüft die Datenbank) |

### Beispielaufrufe

```bash
# Simulation starten
curl -s -X POST http://localhost:8000/api/v1/simulations \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Q4-Prognose",
    "params": {"kind": "gbm", "s0": 100, "mu": 0.07, "sigma": 0.25},
    "n_paths": 2000,
    "n_steps": 252,
    "seed": 42,
    "threshold": 120
  }'

# CSV hochladen
curl -X POST http://localhost:8000/api/v1/datasets \
  -F "file=@data/sample_measurements.csv;type=text/csv" \
  -F "name=Laborlauf Mai"

# Plattformmetriken
curl -s http://localhost:8000/api/v1/overview

# Vollständiger End-to-End-Test
python scripts/smoke_test.py --base-url http://localhost:8000
```

`scripts/smoke_test.py` durchläuft die drei vollständigen Abläufe (Simulation, ETL und Metriken) und liefert einen
Exit-Code ungleich null, wenn etwas fehlschlägt: Es ist dasselbe Skript, das die CI gegen den dockerisierten
Stack ausführt.

<details>
<summary><b>Beispielantwort</b></summary>

```json
{
  "id": "20b2da33-560f-4be5-ae65-b2a085806263",
  "name": "Q4-Prognose",
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

</details>

---

## Mathematische Modelle

**Geometrische Brownsche Bewegung** — multiplikatives Wachstum, Preise, Bevölkerung:

```
S(t+Δt) = S(t) · exp[(μ − σ²/2)·Δt + σ·√Δt·Z]
```

**Ornstein-Uhlenbeck** — Prozess mit Mean-Reversion, korreliertes Rauschen:

```
X(t+Δt) = X(t)·e^(−θΔt) + μ·(1 − e^(−θΔt)) + σ·√((1 − e^(−2θΔt)) / 2θ)·Z
```

**Statische Normalverteilung** — Unsicherheitsfortpflanzung einer Messung:

```
X ~ N(μ, σ²)
```

Alle Pfade werden vektorisiert erzeugt (ohne Schleife über die Pfade). Bei OU läuft die Schleife über die
Zeitschritte, mit vektorisierten Operationen über alle Pfade gleichzeitig.

> [!IMPORTANT]
> **Reproduzierbarkeit:** `numpy.random.default_rng(seed)` garantiert, dass dasselbe Tripel
> `(params, n_paths, n_steps, seed)` exakt dieselben Werte erzeugt. Ein Integrationstest erstellt zwei Läufe
> mit demselben Seed und vergleicht die gespeicherten Endwerte.

**Berechnete Metriken:** Mittelwert, Standardabweichung, Min./Max., Perzentile 5/25/50/75/95, VaR zu 95 %,
Expected Shortfall zu 95 %, Wahrscheinlichkeit einer Überschreitung der Schwelle und Histogramm mit 24 Bins.

---

## ETL-Pipeline

Beim Hochladen einer CSV:

1. **Formaterkennung** — Trennzeichen `,`, `;` oder Tabulator; UTF-8-Encoding (mit BOM) und Fallback auf CP1252.
2. **Schemavalidierung** — Pflichtspalten `timestamp` und `value` (konfigurierbare Namen); `variable` und `unit` optional.
3. **Typisierung** — ISO-8601- oder Unix-Sekunden-Zeitstempel; numerische Werte. Zeilen, die nicht konvertiert
   werden können, werden **verworfen und gezählt**, nicht imputiert.
4. **Deduplizierung** nach `(variable, timestamp)`, wobei die letzte Messung erhalten bleibt.
5. **Ausreißererkennung** nach IQR-Regel (1,5 × IQR) **pro Variable**: Sie werden mit `is_outlier` markiert,
   nicht entfernt, um experimentelle Evidenz nicht zu zerstören.
6. **Nachvollziehbarkeit** — SHA-256-Prüfsumme der Datei, Anzahl gelesener/verworfener/duplizierter Zeilen,
   Zeitbereich und Statistiken pro Variable.
7. **Persistenz** in Batches von 5.000 Zeilen innerhalb einer Transaktion.

Der Endpoint `/stats` **berechnet** die Aggregate mit SQL neu (`avg`, `stddev_samp`, `min`, `max`,
`sum(case ...)`), statt sich blind auf das gespeicherte JSON zu verlassen: eine günstige Konsistenzprüfung.

Beispiel mit dem enthaltenen synthetischen Datensatz (1.443 Zeilen): 1.438 gespeichert, 3 verworfen
(2 fehlende Werte + 1 fehlerhafter Zeitstempel), 2 Duplikate entfernt und 4 Ausreißer markiert.

---

## Datenbank

```
simulation_runs ──< simulation_paths
datasets        ──< measurements
```

| Tabelle | Zweck | Details |
|---|---|---|
| `simulation_runs` | Lauf und seine Zusammenfassung | `params`, `summary` und `trajectory_sample` in JSONB, Status, Dauer, Seed |
| `simulation_paths` | Statistiken pro Pfad | Zusammengesetzter PK `(run_id, path_index)`, FK mit `ON DELETE CASCADE`, Index `(run_id, terminal_value)` |
| `datasets` | Eingelesene CSV | Prüfsumme, Qualitätszähler, Statistiken in JSONB |
| `measurements` | Beobachtungen im Long-Format | Zusammengesetzter Index `(dataset_id, variable, recorded_at)` |

**Warum die Endwerte in Zeilen und nicht in einem JSONB stehen:** Sie ermöglichen Paginierung, Indexierung und
SQL-Aggregation, ohne den gesamten Lauf in den Speicher zu laden. JSONB bleibt für Strukturen mit variabler
Form (Parameter und Zusammenfassung) reserviert.

**Warum die Pfade begrenzt gespeichert werden:** Die Engine berechnet alle Pfade im Speicher, aber
`trajectory_sample` behält maximal 25 Pfade × 300 Schritte (~7.500 Floats), damit das Frontend das Diagramm
zeichnen kann, ohne Millionen von Werten pro Lauf zu speichern.

---

## Tests

```bash
# Nur Unit-Tests (keine Datenbank erforderlich)
pytest tests/unit

# Alles (erfordert PostgreSQL)
export MC_DATABASE_URL="postgresql+psycopg://montecarlo:montecarlo@localhost:5432/montecarlo_test"
pytest --cov=app --cov-report=term-missing

# Streamlit-UI (keine API erforderlich; nutzt AppTest)
pytest frontend/tests
```

- **56 Backend-Tests** und **2 UI-Tests** mit **96 %** Zeilenabdeckung.
- Unit-Tests: stochastische Engines (Formen, Momente, Reproduzierbarkeit), ETL (Encoding, Trennzeichen,
  Ausreißer, Verwürfe), Payload-Validierung.
- Integration: vollständige API gegen echtes PostgreSQL, mit von **Alembic** migrierter Datenbank
  (nicht `create_all`), damit auch die Migrationen getestet werden.
- Isolation: Das Schema wird vor jedem Test geleert.
- **Schutz:** Das Session-Fixture verweigert die Ausführung, wenn der Datenbankname nicht auf `_test` endet,
  da es `DROP SCHEMA public CASCADE` ausführt.

---

## CI/CD

`.github/workflows/ci.yml` definiert vier Jobs:

1. **quality** — `ruff check` und `ruff format --check`.
2. **test** — PostgreSQL 16 als Service-Container, `pytest` mit Coverage und Upload von `coverage.xml` als Artefakt.
3. **docker** — `docker compose up --build --wait`, `scripts/smoke_test.py` gegen den echten Stack, Logs bei
   Fehlern und immer `down -v`.
4. **frontend** — installiert `frontend/requirements.txt` und führt die UI-Tests mit `AppTest` aus, ohne die API
   zu benötigen.

In einem **öffentlichen** Repository sind die GitHub-Actions-Minuten kostenlos; in einem privaten umfasst der
Free-Plan 2.000 Minuten/Monat, mehr als genug für diese Pipeline.

---

## Designentscheidungen

<details open>
<summary><b>Skalierung und Grenzen</b></summary>

- **Synchrone Ausführung mit expliziten Grenzen.** Ein Lauf mit 2.000 Pfaden × 252 Schritten dauert ~40 ms,
  daher ist eine Warteschlange nicht sinnvoll. Die Grenzen (`n_paths ≤ 20.000`, `n_steps ≤ 5.000`,
  `n_paths × n_steps ≤ 2.500.000`) schützen CPU und Speicher und liefern 422 mit einer klaren Meldung.
  Bei wachsendem Bedarf sind Celery/ARQ und ein Status `queued` der natürliche nächste Schritt.

</details>

<details>
<summary><b>Persistenz und Datenintegrität</b></summary>

- **Der Lauf wird vor der Berechnung persistiert.** Wenn der Prozess während der Ausführung abbricht, bleibt
  eine auditierbare `running`-Zeile; schlägt die Engine fehl, wird der Lauf mit dem Fehler als `failed`
  markiert, was ein Integrationstest prüft.
- **Batch-Insert.** `execute(insert(...), rows)` mit *executemany* statt `add_all`, um nicht Tausende
  ORM-Objekte zu materialisieren.
- **Alembic ist die einzige Quelle des Schemas.** Der Container migriert beim Start; die Tests migrieren von
  Grund auf. In Produktion gibt es kein `create_all`.

</details>

<details>
<summary><b>Wissenschaftliche Genauigkeit und Betrieb</b></summary>

- **Expliziter Seed.** Ohne Reproduzierbarkeit ist keine wissenschaftliche Prüfung möglich. `seed` wird in der
  Zeile gespeichert.
- **Ausreißer markiert, nicht gelöscht.** Das Entfernen eines Extremwerts kann genau das untersuchte Phänomen
  verbergen.
- **Non-Root-Container und Healthchecks.** `appuser` (UID 10001), eigener *Healthcheck* des Images und
  `depends_on: condition: service_healthy` in Compose.
- **Domänenfehler getrennt von HTTP.** Die Dienste werfen `AppError`; ein Handler übersetzt sie in JSON mit
  `detail` und `context`.

</details>

---

## Projektstruktur

```text
.
├── app/
│   ├── api/routes/          # simulations, datasets, overview, health
│   ├── core/                # Konfiguration, Fehler, Logging
│   ├── db/                  # Engine, Session und ORM-Modelle
│   ├── schemas/             # Pydantic-Modelle für Ein- und Ausgabe
│   ├── services/            # Monte-Carlo-Engine, ETL und Orchestrierung
│   └── main.py              # App-Factory + Lifespan
├── alembic/                 # versionierte Migrationen
├── tests/
│   ├── unit/
│   └── integration/
├── frontend/                # Streamlit-App + UI-Tests (AppTest)
│   ├── app.py
│   └── tests/
├── scripts/                 # Datengenerator und Smoke-Test
├── data/                    # synthetischer Beispieldatensatz
├── docs/                    # Deployment-Anleitung Render + Render Postgres
├── docker/entrypoint.sh
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── pyproject.toml
└── .github/workflows/ci.yml
```

---

## Grenzen und nächste Schritte

- **Authentifizierung und Nutzerquoten** (API-Keys oder JWT), bevor der Dienst öffentlich angeboten wird.
- **Job-Queue** für große Läufe, mit Status `queued`/`running` und Benachrichtigung.
- **Objektspeicher** (S3/MinIO), um die ursprüngliche CSV zu behalten statt nur der normalisierten Messungen.
- **Observability**: Prometheus-Metriken (`/metrics`), OpenTelemetry-Traces und strukturierte Logs.
- **Cursor-Paginierung** in `measurements` für Datensätze mit Millionen Zeilen.
- **Streaming-Verarbeitung** für CSVs, die das aktuelle Limit von 200.000 Zeilen überschreiten.

---

## Kosten

Der gesamte Stack ist freie Software, und das Projekt kann **ohne Kosten** entwickelt, getestet und
veröffentlicht werden:

| Dienst | Kostenlose Option |
|---|---|
| Python, FastAPI, SQLAlchemy, pandas, NumPy, pytest | Open Source |
| PostgreSQL | Lokales Docker oder Free-Tier von **Render Postgres** / **Neon** / **Supabase** |
| Git + GitHub | Kostenlose öffentliche und private Repositories |
| GitHub Actions | Kostenlos in öffentlichen Repos; 2.000 Min./Monat in privaten (Free-Plan) |
| Docker Desktop | Kostenlos für persönliche, Bildungs- und kleine kommerzielle Nutzung* |

\* Vollständig freie Alternativen ohne Lizenz: Rancher Desktop, Podman Desktop oder Docker Engine unter Linux.

Die *Free-Tiers* ändern sich mit der Zeit: Prüfen Sie die Limits vor dem Deployment. Für Repository und Demo
reicht `docker compose up`.

---

## Lizenz

MIT — siehe [LICENSE](LICENSE).

<div align="center">

<br />

**MonteCarlo Lab** · gebaut mit FastAPI, SQLAlchemy, NumPy und Streamlit

<sub>Wenn dir das Projekt gefällt, hinterlass einen ⭐ im Repository.</sub>

</div>
