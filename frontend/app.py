"""Streamlit frontend for the MonteCarlo Lab API.

Run it locally with::

    streamlit run frontend/app.py

The API base URL defaults to ``http://localhost:8000`` and can be overridden
with the ``API_BASE_URL`` Streamlit secret (Community Cloud) or with the
``MC_API_BASE_URL`` environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import altair as alt
import httpx
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="MonteCarlo Lab",
    page_icon=":material/science:",
    layout="wide",
)

API_PREFIX = "/api/v1"
DEFAULT_API_URL = "http://localhost:8000"

MAX_PATHS = 20_000
MAX_STEPS = 5_000
MAX_CELLS = 2_500_000

PRIMARY = "#0F766E"
ACCENT = "#D97706"
DANGER = "#DC2626"
MUTED = "#64748B"
GRID = "#E2E8F0"

HISTORY_LIMIT = 50
MAX_MEASUREMENT_ROWS = 10_000

STATUS_LABELS = {
    "pending": "Ausstehend",
    "running": "Läuft",
    "completed": "Abgeschlossen",
    "failed": "Fehlgeschlagen",
}
STATUS_COLORS = {
    "pending": "gray",
    "running": "blue",
    "completed": "green",
    "failed": "red",
}

MODELS: dict[str, dict[str, str]] = {
    "GBM": {
        "kind": "gbm",
        "description": (
            "Geometrische Brownsche Bewegung: multiplikatives Wachstum bei "
            "konstanter Volatilität. Das klassische Modell für Vermögenspreise."
        ),
    },
    "Ornstein-Uhlenbeck": {
        "kind": "ou",
        "description": (
            "Prozess mit Mean-Reversion: Die Reihe wird mit Geschwindigkeit θ zum "
            "Mittelwert μ gezogen. Nützlich für physikalische Größen, die zu ihrem "
            "Gleichgewicht zurückkehren."
        ),
    },
    "Normal": {
        "kind": "normal",
        "description": (
            "Statische Unsicherheitsfortpflanzung: eine Ziehung N(μ, σ²) pro "
            "Pfad, ohne Zeitdimension."
        ),
    },
}


class ApiError(Exception):
    """An error returned by the API or raised while connecting to it."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


def default_api_url() -> str:
    """Return the configured API URL, falling back to localhost."""
    try:
        return str(st.secrets["API_BASE_URL"]).rstrip("/")
    except Exception:
        return os.getenv("MC_API_BASE_URL", DEFAULT_API_URL).rstrip("/")


@st.cache_resource(show_spinner=False)
def api_client(base_url: str) -> httpx.Client:
    """One pooled HTTP client per API URL for the lifetime of the server."""
    return httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(180.0, connect=10.0),
        headers={"User-Agent": "montecarlo-lab-streamlit/0.1"},
    )


def _error_detail(detail: Any) -> str:
    """Flatten FastAPI's error payload into a readable message."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        messages: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                location = [
                    str(part)
                    for part in item.get("loc", ())
                    if part not in {"body", "query", "path"}
                ]
                message = str(item.get("msg", "ungültiger Wert"))
                messages.append(f"{' → '.join(location)}: {message}" if location else message)
            else:
                messages.append(str(item))
        return "\n".join(messages)
    return str(detail)


def api_request(
    base_url: str,
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    """Call the API and raise ``ApiError`` with a human-readable message."""
    try:
        response = api_client(base_url).request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(
            f"Verbindung zur API unter {base_url} fehlgeschlagen. Prüfen Sie, ob der Dienst läuft."
        ) from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        detail = payload.get("detail") if isinstance(payload, dict) else None
        message = _error_detail(detail) if detail else f"HTTP-Fehler {response.status_code}"
        raise ApiError(message, status_code=response.status_code, detail=detail)

    if response.status_code == 204:
        return None
    return response.json()


def render_api_error(error: ApiError) -> None:
    st.error(str(error))
    if error.detail and not isinstance(error.detail, str):
        with st.expander("Fehlerdetails", icon=":material/bug_report:"):
            st.json(error.detail)


# ---------------------------------------------------------------------------
# Cached API loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=15, show_spinner="Verbinde mit der API…")
def load_api_status(base_url: str) -> dict[str, Any]:
    try:
        health = api_request(base_url, "GET", "/health")
        readiness = api_request(base_url, "GET", "/health/ready")
        return {"health": health, "ready": readiness, "error": None}
    except ApiError as exc:
        return {"health": None, "ready": None, "error": str(exc)}


@st.cache_data(ttl=30, show_spinner=False)
def load_overview(base_url: str) -> dict[str, Any] | None:
    try:
        return api_request(base_url, "GET", f"{API_PREFIX}/overview")
    except ApiError:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def load_run(base_url: str, run_id: str) -> dict[str, Any]:
    return api_request(base_url, "GET", f"{API_PREFIX}/simulations/{run_id}")


@st.cache_data(ttl=600, show_spinner=False)
def load_histogram(base_url: str, run_id: str) -> dict[str, Any]:
    return api_request(base_url, "GET", f"{API_PREFIX}/simulations/{run_id}/histogram")


@st.cache_data(ttl=600, show_spinner=False)
def load_trajectories(base_url: str, run_id: str) -> dict[str, Any]:
    return api_request(base_url, "GET", f"{API_PREFIX}/simulations/{run_id}/trajectories")


@st.cache_data(ttl=15, show_spinner=False)
def load_runs(base_url: str, run_status: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": HISTORY_LIMIT}
    if run_status:
        params["status"] = run_status
    return api_request(base_url, "GET", f"{API_PREFIX}/simulations", params=params)


@st.cache_data(ttl=20, show_spinner=False)
def load_datasets(base_url: str) -> dict[str, Any]:
    return api_request(base_url, "GET", f"{API_PREFIX}/datasets", params={"limit": 50})


@st.cache_data(ttl=20, show_spinner=False)
def load_dataset_stats(base_url: str, dataset_id: str) -> dict[str, Any]:
    return api_request(base_url, "GET", f"{API_PREFIX}/datasets/{dataset_id}/stats")


@st.cache_data(ttl=30, show_spinner=False)
def load_measurements(
    base_url: str,
    dataset_id: str,
    variable: str,
    max_rows: int = MAX_MEASUREMENT_ROWS,
) -> tuple[pd.DataFrame, int, int]:
    rows: list[dict[str, Any]] = []
    total: int | None = None
    offset = 0

    while total is None or offset < min(total, max_rows):
        page = api_request(
            base_url,
            "GET",
            f"{API_PREFIX}/datasets/{dataset_id}/measurements",
            params={"variable": variable, "limit": 1_000, "offset": offset},
        )
        rows.extend(page["items"])
        total = int(page["total"])
        if not page["items"]:
            break
        offset += len(page["items"])

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["recorded_at"] = pd.to_datetime(frame["recorded_at"], utc=True)
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame.sort_values("recorded_at").reset_index(drop=True)

    return frame, int(total or 0), len(rows)


def refresh_run_caches() -> None:
    """Invalidate the caches that change when a new run is persisted."""
    load_runs.clear()
    load_overview.clear()


def refresh_dataset_caches() -> None:
    """Invalidate the caches that change when a new dataset is uploaded."""
    load_datasets.clear()
    load_overview.clear()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _de_number(text: str) -> str:
    """Convert an English-formatted number (1,234.56) to German notation (1.234,56)."""
    if "e" in text or "E" in text:
        return text
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_decimal(value: float, significant: int = 6) -> str:
    """Format a number with German thousands and decimal separators."""
    return _de_number(f"{value:,.{significant}g}")


def fmt_int(value: int) -> str:
    """Format an integer with German thousands separators."""
    return f"{value:,.0f}".replace(",", ".")


def fmt_percent(value: float) -> str:
    """Format a fraction as a German percentage, e.g. ``28,00 %``."""
    return _de_number(f"{value * 100:,.2f}") + " %"


def fmt_number(value: float | None) -> str:
    if value is None:
        return "—"
    return fmt_decimal(value)


def fmt_metric(value: float | None) -> str:
    if value is None:
        return "—"
    return fmt_decimal(value)


def fmt_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC")
        return stamp.strftime("%d.%m.%Y %H:%M UTC")
    except (ValueError, TypeError):
        return value


def fmt_duration(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{fmt_int(value)} ms"


def style_chart(chart: alt.Chart) -> alt.Chart:
    """Apply the app's neutral, readable chart styling."""
    return chart.configure_view(strokeWidth=0).configure_axis(
        grid=True,
        gridColor=GRID,
        gridOpacity=0.85,
        domainColor=GRID,
        tickColor=GRID,
        labelColor=MUTED,
        titleColor=MUTED,
        labelFontSize=11,
        titleFontSize=11,
        titleFontWeight="normal",
    )


def status_badge(status: str) -> None:
    st.badge(
        STATUS_LABELS.get(status, status),
        color=STATUS_COLORS.get(status, "gray"),
        icon=":material/circle:",
    )


# ---------------------------------------------------------------------------
# Simulation results (shared by the simulation and history tabs)
# ---------------------------------------------------------------------------


def render_simulation_results(base_url: str, run_id: str) -> None:
    """Render the status, KPIs, charts and statistics for one run."""
    try:
        run = load_run(base_url, run_id)
    except ApiError as exc:
        render_api_error(exc)
        return

    status = run["status"]
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(f"#### {run['name']}")
        status_badge(status)

    st.caption(
        f"`{run['id'][:8]}` · {run['model'].upper()} · "
        f"Seed {fmt_int(run['seed']) if run['seed'] is not None else 'zufällig'} · "
        f"{fmt_datetime(run['created_at'])}"
    )

    if status != "completed":
        if status == "failed":
            st.error(run.get("error") or "Der Lauf ist ohne Fehlermeldung fehlgeschlagen.")
        else:
            st.info(
                "Die Simulation hat noch keine Ergebnisse. "
                f"Aktueller Status: {STATUS_LABELS.get(status, status)}."
            )
        return

    summary = run.get("summary") or {}
    threshold = run.get("threshold")

    metric_columns = st.columns(5)
    metric_columns[0].metric("Mittelwert", fmt_metric(summary.get("mean")), border=True)
    metric_columns[1].metric("Standardabweichung", fmt_metric(summary.get("std")), border=True)
    metric_columns[2].metric("P05", fmt_metric(summary.get("p05")), border=True)
    metric_columns[3].metric("Median", fmt_metric(summary.get("p50")), border=True)
    metric_columns[4].metric("P95", fmt_metric(summary.get("p95")), border=True)

    chart_column, series_column = st.columns(2, gap="large")

    with chart_column:
        with st.container(border=True):
            st.markdown("**Verteilung der Endwerte**")
            try:
                histogram = load_histogram(base_url, run_id)
            except ApiError as exc:
                render_api_error(exc)
            else:
                edges = histogram["bins"]
                hist_frame = pd.DataFrame(
                    {
                        "start": edges[:-1],
                        "end": edges[1:],
                        "count": histogram["counts"],
                    }
                )
                hist_frame["interval"] = [
                    f"{fmt_decimal(start, 4)} – {fmt_decimal(end, 4)}"
                    for start, end in zip(hist_frame["start"], hist_frame["end"], strict=True)
                ]

                bars = (
                    alt.Chart(hist_frame)
                    .mark_bar(color=PRIMARY)
                    .encode(
                        x=alt.X("start:Q", title="Endwert"),
                        x2="end:Q",
                        y=alt.Y("count:Q", title="Pfade"),
                        tooltip=[
                            alt.Tooltip("interval:N", title="Intervall"),
                            alt.Tooltip("count:Q", title="Pfade", format=","),
                        ],
                    )
                )
                mean_rule = (
                    alt.Chart(pd.DataFrame({"x": [summary["mean"]]}))
                    .mark_rule(color=ACCENT, strokeDash=[5, 3], strokeWidth=1.6)
                    .encode(x="x:Q")
                )
                layers: list[alt.Chart] = [bars, mean_rule]
                caption = "Gestrichelte bernsteinfarbene Linie: Mittelwert."

                if threshold is not None:
                    threshold_rule = (
                        alt.Chart(pd.DataFrame({"x": [threshold]}))
                        .mark_rule(color=DANGER, strokeDash=[2, 3], strokeWidth=1.4)
                        .encode(x="x:Q")
                    )
                    layers.append(threshold_rule)
                    caption = (
                        "Gestrichelte bernsteinfarbene Linie: Mittelwert · rote Linie: Schwelle."
                    )

                chart = style_chart(alt.layer(*layers).properties(height=300))
                st.altair_chart(
                    chart,
                    alt=(
                        f"Histogramm der Endwerte mit Mittelwert "
                        f"{fmt_decimal(summary['mean'], 4)}, "
                        f"verteilt auf {len(histogram['counts'])} Intervalle"
                    ),
                )
                st.caption(caption)

    with series_column:
        with st.container(border=True):
            st.markdown("**Simulierte Pfade**")
            try:
                trajectories = load_trajectories(base_url, run_id)
            except ApiError as exc:
                render_api_error(exc)
            else:
                paths = trajectories["paths"]
                steps = trajectories["steps"]

                if run["model"] == "normal" or len(steps) <= 1:
                    normal_frame = pd.DataFrame(
                        {
                            "path": [f"#{index + 1}" for index in range(len(paths))],
                            "value": [path[0] for path in paths],
                        }
                    )
                    chart = style_chart(
                        alt.Chart(normal_frame)
                        .mark_tick(color=PRIMARY, thickness=2, size=24)
                        .encode(
                            x=alt.X("value:Q", title="Wert"),
                            y=alt.Y("path:O", title=None, axis=None),
                            tooltip=[
                                alt.Tooltip("path:N", title="Pfad"),
                                alt.Tooltip("value:Q", title="Wert", format=",.4f"),
                            ],
                        )
                        .properties(height=300)
                    )
                    st.altair_chart(
                        chart,
                        alt=(
                            "Stichproben des Normal-Modells: eine Ziehung pro Pfad "
                            "auf einer horizontalen Achse"
                        ),
                    )
                    st.caption(
                        "Das Normal-Modell hat keine Zeitdimension; "
                        "jeder Pfad ist eine einzelne Ziehung."
                    )
                else:
                    dt = trajectories.get("dt") or 1.0
                    time_label = "Zeit (Jahre)" if dt != 1.0 else "Schritt"
                    records = [
                        {
                            "path": f"#{path_index + 1}",
                            "step": step,
                            "time": step * dt,
                            "value": value,
                        }
                        for path_index, path in enumerate(paths)
                        for step, value in zip(steps, path, strict=True)
                    ]
                    frame = pd.DataFrame(records)

                    lines = (
                        alt.Chart(frame)
                        .mark_line(strokeWidth=1, opacity=0.45)
                        .encode(
                            x=alt.X("time:Q", title=time_label),
                            y=alt.Y(
                                "value:Q",
                                title="Wert",
                                scale=alt.Scale(zero=False),
                            ),
                            detail="path:N",
                            tooltip=[
                                alt.Tooltip("path:N", title="Pfad"),
                                alt.Tooltip("step:Q", title="Schritt"),
                                alt.Tooltip("value:Q", title="Wert", format=",.4f"),
                            ],
                        )
                    )
                    mean_frame = frame.groupby(["step", "time"], as_index=False)["value"].mean()
                    mean_line = (
                        alt.Chart(mean_frame)
                        .mark_line(color=ACCENT, strokeWidth=2.4)
                        .encode(x="time:Q", y="value:Q")
                    )
                    chart = style_chart((lines + mean_line).properties(height=300).interactive())
                    st.altair_chart(
                        chart,
                        alt=(
                            f"{len(paths)} Pfade über {len(steps)} Zeitpunkte, "
                            "mit bernsteinfarbenem Mittelwert"
                        ),
                    )
                    st.caption(
                        f"{len(paths)} von {fmt_int(trajectories['total_paths'])} "
                        "Pfaden abgetastet · bernsteinfarbene Linie: Mittelwert."
                    )

    st.write("")
    stats_column, details_column = st.columns([3, 2], gap="large")

    with stats_column:
        with st.container(border=True):
            st.markdown("**Statistiken der Endwerte**")
            stats_rows: list[tuple[str, str]] = [
                ("Mittelwert", fmt_number(summary.get("mean"))),
                ("Standardabweichung", fmt_number(summary.get("std"))),
                ("Minimum", fmt_number(summary.get("minimum"))),
                ("P05", fmt_number(summary.get("p05"))),
                ("P25", fmt_number(summary.get("p25"))),
                ("Median (P50)", fmt_number(summary.get("p50"))),
                ("P75", fmt_number(summary.get("p75"))),
                ("P95", fmt_number(summary.get("p95"))),
                ("Maximum", fmt_number(summary.get("maximum"))),
                ("VaR 95 % (P05)", fmt_number(summary.get("var_95"))),
                (
                    "Expected Shortfall 95 %",
                    fmt_number(summary.get("expected_shortfall_95")),
                ),
            ]
            if summary.get("prob_above_threshold") is not None:
                stats_rows.append(
                    (
                        "P(X > Schwelle)",
                        fmt_percent(summary["prob_above_threshold"]),
                    )
                )

            st.dataframe(
                pd.DataFrame(stats_rows, columns=["Kennzahl", "Wert"]),
                hide_index=True,
                height="content",
                alt="Tabelle mit den Simulationsstatistiken",
            )

    with details_column:
        with st.container(border=True):
            st.markdown("**Lauf**")
            details_rows = [
                ("Modell", run["model"].upper()),
                ("Pfade", fmt_int(run["n_paths"])),
                ("Schritte", fmt_int(run["n_steps"])),
                (
                    "Seed",
                    fmt_int(run["seed"]) if run["seed"] is not None else "zufällig",
                ),
                ("Schwelle", fmt_number(threshold)),
                ("Dauer", fmt_duration(run.get("duration_ms"))),
                ("Beendet", fmt_datetime(run.get("finished_at"))),
            ]
            st.dataframe(
                pd.DataFrame(details_rows, columns=["Feld", "Wert"]),
                hide_index=True,
                height="content",
                alt="Tabelle mit den Laufparametern",
            )

    with st.expander("Parameter und JSON-Antwort", icon=":material/data_object:"):
        st.json(run)


# ---------------------------------------------------------------------------
# Simulation tab
# ---------------------------------------------------------------------------


def render_simulation_tab(api_url: str) -> None:
    st.subheader("Neue Simulation")
    st.caption(
        "Die Parameter werden in der API validiert. Jeder Lauf wird in PostgreSQL "
        "gespeichert und ist mit seinem Seed reproduzierbar."
    )

    model_label = (
        st.segmented_control(
            "Stochastisches Modell",
            options=list(MODELS),
            default="GBM",
            required=True,
            key="simulation_model",
        )
        or "GBM"
    )
    model = MODELS[model_label]
    st.caption(model["description"])

    with st.form("simulation_form", border=True):
        name = st.text_input(
            "Name der Simulation",
            placeholder=f"{model_label} · 1.000 Pfade",
            max_chars=200,
            key="simulation_name",
        )

        st.markdown("**Modellparameter**")
        if model["kind"] == "gbm":
            parameter_columns = st.columns(4)
            s0 = parameter_columns[0].number_input(
                "Startwert (S₀)",
                min_value=0.01,
                value=100.0,
                step=1.0,
                help="Ausgangspreis oder -größe. Muss größer als 0 sein.",
                key="gbm_s0",
            )
            mu = parameter_columns[1].number_input(
                "Jährliche Drift (μ)",
                value=0.08,
                step=0.01,
                format="%.4f",
                help="Erwartete Wachstumsrate pro Jahr.",
                key="gbm_mu",
            )
            sigma = parameter_columns[2].number_input(
                "Jährliche Volatilität (σ)",
                min_value=0.001,
                max_value=5.0,
                value=0.20,
                step=0.01,
                format="%.4f",
                help="Jährliche Volatilität. Muss größer als 0 und höchstens 5 sein.",
                key="gbm_sigma",
            )
            dt = parameter_columns[3].number_input(
                "Zeitschritt (dt)",
                min_value=0.0001,
                max_value=1.0,
                value=1 / 252,
                step=0.0001,
                format="%.6f",
                help="Jahresanteil zwischen zwei Punkten. 1/252 entspricht einem Börsentag.",
                key="gbm_dt",
            )
            params: dict[str, Any] = {
                "kind": "gbm",
                "s0": s0,
                "mu": mu,
                "sigma": sigma,
                "dt": dt,
            }
            n_steps_default = 252
            show_steps = True
        elif model["kind"] == "ou":
            parameter_columns = st.columns(5)
            x0 = parameter_columns[0].number_input(
                "Startwert (x₀)",
                value=0.0,
                step=1.0,
                format="%.4f",
                help="Wert der Reihe zum Startzeitpunkt.",
                key="ou_x0",
            )
            mu = parameter_columns[1].number_input(
                "Langfristiger Mittelwert (μ)",
                value=0.0,
                step=1.0,
                format="%.4f",
                help="Niveau, zu dem der Prozess tendenziell zurückkehrt.",
                key="ou_mu",
            )
            theta = parameter_columns[2].number_input(
                "Reversionsrate (θ)",
                min_value=0.0001,
                value=1.5,
                step=0.1,
                format="%.4f",
                help="Geschwindigkeit der Mean-Reversion. Muss größer als 0 sein.",
                key="ou_theta",
            )
            sigma = parameter_columns[3].number_input(
                "Volatilität (σ)",
                min_value=0.0001,
                max_value=100.0,
                value=0.30,
                step=0.05,
                format="%.4f",
                help="Rauschintensität. Muss größer als 0 sein.",
                key="ou_sigma",
            )
            dt = parameter_columns[4].number_input(
                "Zeitschritt (dt)",
                min_value=0.0001,
                max_value=1.0,
                value=1 / 252,
                step=0.0001,
                format="%.6f",
                help="Jahresanteil zwischen zwei Punkten.",
                key="ou_dt",
            )
            params = {
                "kind": "ou",
                "x0": x0,
                "mu": mu,
                "theta": theta,
                "sigma": sigma,
                "dt": dt,
            }
            n_steps_default = 252
            show_steps = True
        else:
            parameter_columns = st.columns(2)
            mean = parameter_columns[0].number_input(
                "Mittelwert (μ)",
                value=100.0,
                step=1.0,
                format="%.4f",
                help="Zentrum der Normalverteilung.",
                key="normal_mean",
            )
            std = parameter_columns[1].number_input(
                "Standardabweichung (σ)",
                min_value=0.0001,
                value=15.0,
                step=1.0,
                format="%.4f",
                help="Streuung der Verteilung. Muss größer als 0 sein.",
                key="normal_std",
            )
            params = {"kind": "normal", "mean": mean, "std": std}
            n_steps_default = 1
            show_steps = False

        st.divider()
        st.markdown("**Simulationsumfang**")
        workload_columns = st.columns(4 if show_steps else 3)
        n_paths = workload_columns[0].number_input(
            "Pfade",
            min_value=100,
            max_value=MAX_PATHS,
            value=1_000,
            step=100,
            help="Anzahl der zu simulierenden Pfade. Die API akzeptiert 100 bis 20.000.",
            key="n_paths",
        )
        if show_steps:
            n_steps = workload_columns[1].number_input(
                "Schritte",
                min_value=1,
                max_value=MAX_STEPS,
                value=n_steps_default,
                step=1,
                help="Punkte pro Pfad. Die API akzeptiert maximal 5.000.",
                key="n_steps",
            )
            seed_column = workload_columns[2]
            threshold_column = workload_columns[3]
        else:
            n_steps = 1
            seed_column = workload_columns[1]
            threshold_column = workload_columns[2]

        seed = seed_column.number_input(
            "Seed",
            min_value=0,
            max_value=2**53 - 1,
            value=42,
            step=1,
            help="Gleicher Seed und gleiche Parameter erzeugen exakt dasselbe Ergebnis.",
            key="seed",
        )
        threshold = threshold_column.number_input(
            "Schwelle (optional)",
            value=None,
            step=1.0,
            format="%.4f",
            placeholder="Keine Schwelle",
            help="Wenn angegeben, berechnet die API P(X > Schwelle).",
            key="threshold",
        )

        submitted = st.form_submit_button(
            "Simulation starten",
            type="primary",
            icon=":material/play_arrow:",
        )

    st.caption(
        f"Instanzgrenzen: {fmt_int(MAX_PATHS)} Pfade, {fmt_int(MAX_STEPS)} Schritte "
        f"und {fmt_int(MAX_CELLS)} Zellen (Pfade × Schritte) pro Lauf."
    )

    if submitted:
        if n_paths * n_steps > MAX_CELLS:
            st.error(
                f"Die angeforderte Last ({fmt_int(n_paths * n_steps)} Zellen) überschreitet "
                f"das Limit von {fmt_int(MAX_CELLS)}. Reduzieren Sie die Anzahl der Pfade "
                "oder Schritte."
            )
        else:
            payload = {
                "name": name.strip() or f"{model_label} · {fmt_int(n_paths)} Pfade",
                "params": params,
                "n_paths": int(n_paths),
                "n_steps": int(n_steps),
                "seed": int(seed),
                "threshold": threshold,
            }

            status_box = st.status("Simulation wird ausgeführt…", expanded=False)
            try:
                run = api_request(
                    api_url,
                    "POST",
                    f"{API_PREFIX}/simulations",
                    json=payload,
                )
            except ApiError as exc:
                status_box.update(
                    label="Die Simulation konnte nicht ausgeführt werden",
                    state="error",
                    expanded=True,
                )
                render_api_error(exc)
            else:
                st.session_state["last_run_id"] = run["id"]
                st.session_state["history_run"] = run["id"]
                refresh_run_caches()

                if run["status"] == "completed":
                    status_box.update(
                        label=(
                            f"Simulation in {fmt_int(run['duration_ms'])} ms abgeschlossen · "
                            f"{fmt_int(run['n_paths'])} Pfade"
                        ),
                        state="complete",
                    )
                else:
                    status_box.update(
                        label=(
                            "Die Simulation endete mit dem Status "
                            f"„{STATUS_LABELS.get(run['status'], run['status']).lower()}“"
                        ),
                        state="error",
                        expanded=True,
                    )
                    st.error(run.get("error") or "Die Simulation hat keine Ergebnisse geliefert.")

    last_run_id = st.session_state.get("last_run_id")
    if last_run_id:
        st.divider()
        st.subheader("Ergebnisse")
        render_simulation_results(api_url, last_run_id)
    else:
        st.info(
            "Konfigurieren Sie die Parameter und klicken Sie auf **Simulation starten**, "
            "um Histogramm, Pfade und Statistiken zu sehen."
        )


# ---------------------------------------------------------------------------
# Datasets tab
# ---------------------------------------------------------------------------


def render_dataset_upload(api_url: str) -> None:
    with st.form("dataset_upload_form", border=True, clear_on_submit=True):
        st.markdown("**CSV hochladen**")
        upload_columns = st.columns([2, 2, 1, 1])
        uploaded_file = upload_columns[0].file_uploader(
            "CSV-Datei",
            type=["csv"],
            help="Maximal 10 MB. Kodierung, Trennzeichen und Kopfzeile werden erkannt.",
        )
        dataset_name = upload_columns[1].text_input(
            "Name des Datensatzes",
            placeholder="Reaktormessungen",
            max_chars=200,
        )
        default_variable = upload_columns[2].text_input(
            "Standardvariable",
            value="value",
            max_chars=80,
            help="Wird verwendet, wenn die CSV keine Spalte 'variable' enthält.",
        )
        default_unit = upload_columns[3].text_input(
            "Standardeinheit",
            max_chars=32,
            placeholder="bar",
        )

        with st.expander("Erweiterte Spaltenoptionen", icon=":material/tune:"):
            advanced_columns = st.columns(2)
            timestamp_column = advanced_columns[0].text_input(
                "Zeitspalte",
                value="timestamp",
                max_chars=80,
            )
            value_column = advanced_columns[1].text_input(
                "Wertspalte",
                value="value",
                max_chars=80,
            )

        upload_submitted = st.form_submit_button(
            "Verarbeiten und speichern",
            type="primary",
            icon=":material/upload:",
        )

    if upload_submitted:
        if uploaded_file is None:
            st.warning("Wählen Sie eine CSV-Datei aus, bevor Sie sie hochladen.")
        else:
            form_data = {
                "name": dataset_name.strip() or uploaded_file.name,
                "variable": default_variable.strip() or "value",
                "timestamp_column": timestamp_column.strip() or "timestamp",
                "value_column": value_column.strip() or "value",
            }
            if default_unit.strip():
                form_data["unit"] = default_unit.strip()

            status_box = st.status("CSV wird mit Pandas verarbeitet…", expanded=False)
            try:
                dataset = api_request(
                    api_url,
                    "POST",
                    f"{API_PREFIX}/datasets",
                    files={
                        "file": (
                            uploaded_file.name,
                            uploaded_file.getvalue(),
                            uploaded_file.type or "text/csv",
                        )
                    },
                    data=form_data,
                )
            except ApiError as exc:
                status_box.update(
                    label="Die CSV-Datei konnte nicht verarbeitet werden",
                    state="error",
                    expanded=True,
                )
                render_api_error(exc)
            else:
                st.session_state["dataset_choice"] = dataset["id"]
                refresh_dataset_caches()
                status_box.update(
                    label=(
                        f"Datensatz gespeichert · {fmt_int(dataset['row_count'])} Messungen · "
                        f"{fmt_int(dataset['outlier_rows'])} Ausreißer markiert"
                    ),
                    state="complete",
                )
                if dataset.get("rejected_rows"):
                    st.warning(
                        f"{fmt_int(dataset['rejected_rows'])} Zeilen wurden wegen ungültiger "
                        "Zeitstempel oder Werte verworfen. Details finden Sie im ETL-Bericht."
                    )

    sample_path = Path(__file__).resolve().parent.parent / "data" / "sample_measurements.csv"
    if sample_path.exists():
        st.download_button(
            "Beispiel-CSV herunterladen",
            data=sample_path.read_bytes(),
            file_name="sample_measurements.csv",
            mime="text/csv",
            icon=":material/download:",
            type="tertiary",
        )


def render_dataset_details(api_url: str, dataset: dict[str, Any]) -> None:
    try:
        stats = load_dataset_stats(api_url, dataset["id"])
    except ApiError as exc:
        render_api_error(exc)
        return

    st.markdown(f"**{dataset['name']}**")
    st.caption(
        f"`{dataset['id'][:8]}` · {dataset['source_filename']} · "
        f"hochgeladen am {fmt_datetime(dataset['created_at'])} · "
        f"sha256 `{dataset['checksum_sha256'][:12]}…`"
    )

    if dataset.get("status") == "failed":
        st.error(dataset.get("error") or "Der ETL-Prozess ist bei diesem Datensatz fehlgeschlagen.")

    metric_columns = st.columns(4)
    metric_columns[0].metric("Messungen", fmt_int(stats["row_count"]), border=True)
    metric_columns[1].metric("Verworfene Zeilen", fmt_int(stats["rejected_rows"]), border=True)
    metric_columns[2].metric("Ausreißer (IQR)", fmt_int(stats["outlier_rows"]), border=True)
    metric_columns[3].metric("Variablen", fmt_int(len(stats["variables"])), border=True)

    if not stats["variables"]:
        st.info("Dieser Datensatz enthält keine gültigen Variablen.")
        return

    variables_frame = pd.DataFrame(stats["variables"]).rename(
        columns={
            "variable": "Variable",
            "count": "Messungen",
            "mean": "Mittelwert",
            "std": "Standardabweichung",
            "minimum": "Minimum",
            "maximum": "Maximum",
            "outliers": "Ausreißer",
        }
    )
    st.dataframe(
        variables_frame,
        hide_index=True,
        height="content",
        alt="Statistiken pro Variable des Datensatzes",
    )

    variable_names = [item["variable"] for item in stats["variables"]]
    variable_column, _ = st.columns([2, 3])
    selected_variable = variable_column.selectbox(
        "Variable für die Zeitreihe",
        options=variable_names,
        key=f"dataset_variable_{dataset['id']}",
    )

    try:
        frame, total, fetched = load_measurements(api_url, dataset["id"], selected_variable)
    except ApiError as exc:
        render_api_error(exc)
        return

    if frame.empty:
        st.info("Für diese Variable sind keine Messungen verfügbar.")
        return

    with st.container(border=True):
        st.markdown(f"**Zeitreihe · {selected_variable}**")
        unit = frame["unit"].dropna().iloc[0] if frame["unit"].notna().any() else None
        y_title = f"{selected_variable} ({unit})" if unit else selected_variable

        line = (
            alt.Chart(frame)
            .mark_line(color=PRIMARY, strokeWidth=1.4)
            .encode(
                x=alt.X("recorded_at:T", title=None),
                y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=False)),
                tooltip=[
                    alt.Tooltip("recorded_at:T", title="Datum", format="%d.%m.%Y %H:%M"),
                    alt.Tooltip("value:Q", title=selected_variable, format=",.4f"),
                ],
            )
        )
        layers: list[alt.Chart] = [line]

        outliers = frame[frame["is_outlier"]]
        if not outliers.empty:
            outlier_points = (
                alt.Chart(outliers)
                .mark_circle(color=DANGER, size=60, opacity=0.9)
                .encode(
                    x="recorded_at:T",
                    y="value:Q",
                    tooltip=[
                        alt.Tooltip("recorded_at:T", title="Datum", format="%d.%m.%Y %H:%M"),
                        alt.Tooltip("value:Q", title="Ausreißer", format=",.4f"),
                    ],
                )
            )
            layers.append(outlier_points)

        chart = style_chart(alt.layer(*layers).properties(height=320).interactive())
        st.altair_chart(
            chart,
            alt=(
                f"Zeitreihe von {selected_variable} mit {len(outliers)} "
                "rot hervorgehobenen Ausreißern"
            ),
        )
        st.caption(
            f"{fmt_int(fetched)} von {fmt_int(total)} Messungen · rote Punkte: "
            "mit IQR erkannte Ausreißer."
        )

    with st.container(horizontal=True, horizontal_alignment="right"):
        st.download_button(
            "Messungen herunterladen (CSV)",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=f"{dataset['name'][:40].replace(' ', '_')}_{selected_variable}.csv",
            mime="text/csv",
            icon=":material/download:",
            type="tertiary",
        )

    with st.expander(f"Messungen anzeigen ({fmt_int(fetched)})", icon=":material/table_rows:"):
        display_frame = frame.head(500).rename(
            columns={
                "recorded_at": "Datum",
                "variable": "Variable",
                "value": "Wert",
                "unit": "Einheit",
                "is_outlier": "Ausreißer",
            }
        )
        st.dataframe(
            display_frame[["Datum", "Variable", "Wert", "Einheit", "Ausreißer"]],
            hide_index=True,
            height=280,
            alt="Tabelle mit den Messungen des Datensatzes",
        )

    with st.expander("ETL-Bericht des Datensatzes", icon=":material/fact_check:"):
        st.json(dataset)
        st.json(stats)


def render_datasets_tab(api_url: str) -> None:
    st.subheader("Experimentelle Datensätze")
    st.caption(
        "Die Pandas-ETL validiert Datentypen, entfernt Duplikate, markiert Ausreißer "
        "über den Interquartilsabstand (IQR) und protokolliert eine SHA-256-Prüfsumme "
        "der Datei."
    )

    render_dataset_upload(api_url)
    st.divider()

    try:
        datasets = load_datasets(api_url)
    except ApiError as exc:
        render_api_error(exc)
        return

    items = datasets["items"]
    if not items:
        st.info(
            "Noch keine Datensätze vorhanden. Laden Sie eine CSV-Datei hoch oder "
            "verwenden Sie die Beispieldatei."
        )
        return

    by_id = {item["id"]: item for item in items}
    options = list(by_id)
    default_id = st.session_state.get("dataset_choice")
    if default_id not in options:
        default_id = options[0]

    selected_id = st.selectbox(
        "Datensatz",
        options=options,
        index=options.index(default_id),
        format_func=lambda dataset_id: (
            f"{by_id[dataset_id]['name']} · {fmt_int(by_id[dataset_id]['row_count'])} "
            f"Messungen · {fmt_datetime(by_id[dataset_id]['created_at'])}"
        ),
        key="dataset_choice",
    )
    st.divider()
    render_dataset_details(api_url, by_id[selected_id])


# ---------------------------------------------------------------------------
# History tab
# ---------------------------------------------------------------------------


def render_history_tab(api_url: str) -> None:
    st.subheader("Simulationsverlauf")
    st.caption("Jeder Lauf behält seine Parameter, seinen Seed und seine Ergebnisse in PostgreSQL.")

    filter_label = st.segmented_control(
        "Nach Status filtern",
        options=["Alle", "Abgeschlossen", "Fehlgeschlagen"],
        default="Alle",
        key="history_status",
    )
    status_lookup = {"Alle": None, "Abgeschlossen": "completed", "Fehlgeschlagen": "failed"}
    run_status = status_lookup.get(filter_label or "Alle")

    try:
        runs = load_runs(api_url, run_status)
    except ApiError as exc:
        render_api_error(exc)
        return

    items = runs["items"]
    if not items:
        st.info("Keine Läufe entsprechen dem Filter.")
        return

    completed = sum(1 for item in items if item["status"] == "completed")
    failed = sum(1 for item in items if item["status"] == "failed")
    metric_columns = st.columns(3)
    metric_columns[0].metric("Läufe", fmt_int(runs["total"]), border=True)
    metric_columns[1].metric("Abgeschlossen", fmt_int(completed), border=True)
    metric_columns[2].metric("Fehlgeschlagen", fmt_int(failed), border=True)

    table_rows = []
    for item in items:
        summary = item.get("summary") or {}
        table_rows.append(
            {
                "Datum": fmt_datetime(item["created_at"]).replace(" UTC", ""),
                "Name": item["name"],
                "Modell": item["model"].upper(),
                "Status": STATUS_LABELS.get(item["status"], item["status"]),
                "Pfade": item["n_paths"],
                "Schritte": item["n_steps"],
                "Mittelwert": fmt_number(summary.get("mean")),
                "Dauer": fmt_duration(item.get("duration_ms")),
            }
        )

    st.dataframe(
        pd.DataFrame(table_rows),
        hide_index=True,
        height="content",
        alt="Tabelle mit dem Simulationsverlauf",
    )

    by_id = {item["id"]: item for item in items}
    options = list(by_id)
    default_id = st.session_state.get("history_run")
    if default_id not in options:
        default_id = options[0]

    selected_id = st.selectbox(
        "Einen Lauf öffnen",
        options=options,
        index=options.index(default_id),
        format_func=lambda run_id: (
            f"{fmt_datetime(by_id[run_id]['created_at'])} · "
            f"{by_id[run_id]['name']} · "
            f"{STATUS_LABELS.get(by_id[run_id]['status'], by_id[run_id]['status'])}"
        ),
        key="history_run",
    )

    st.divider()
    render_simulation_results(api_url, selected_id)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


with st.sidebar:
    st.markdown("### :material/science: MonteCarlo Lab")
    st.caption("FastAPI · PostgreSQL · Pandas · Streamlit")

    api_url = (
        st.text_input(
            "API-URL",
            value=default_api_url(),
            help="Lokal: http://localhost:8000 · Produktion: die URL von Render.",
        )
        or DEFAULT_API_URL
    ).rstrip("/")

    api_status = load_api_status(api_url)
    if api_status["error"]:
        st.badge("API nicht verfügbar", color="red", icon=":material/cloud_off:")
        with st.expander("Verbindungsdetails", icon=":material/error:"):
            st.caption(api_status["error"])
    else:
        st.badge(
            "API und Datenbank betriebsbereit",
            color="green",
            icon=":material/check_circle:",
        )
        health = api_status["health"]
        st.caption(f"Version {health['version']} · Umgebung `{health['environment']}`")

    with st.container(horizontal=True):
        if st.button("Erneut versuchen", icon=":material/refresh:", type="tertiary"):
            load_api_status.clear()
            st.rerun()
        st.link_button(
            "OpenAPI",
            f"{api_url}/docs",
            icon=":material/menu_book:",
            type="tertiary",
        )

    st.divider()
    st.markdown("**Grenzen pro Lauf**")
    st.caption(
        f"{fmt_int(MAX_PATHS)} Pfade · {fmt_int(MAX_STEPS)} Schritte · "
        f"{fmt_int(MAX_CELLS)} Zellen. Die Läufe sind synchron und werden dauerhaft "
        "gespeichert."
    )
    st.divider()
    st.caption(
        "Backend-Portfolioprojekt: REST-API, Monte-Carlo-Engine mit NumPy, "
        "ETL mit Pandas und Persistenz in PostgreSQL."
    )

st.title(":material/science: MonteCarlo Lab")
st.caption(
    "Simulieren Sie stochastische Prozesse, erkunden Sie ihre Verteilung und "
    "analysieren Sie experimentelle Messungen. Alle Ergebnisse werden in PostgreSQL "
    "gespeichert."
)

overview = load_overview(api_url) if not api_status["error"] else None
if overview:
    overview_columns = st.columns(4)
    overview_columns[0].metric(
        "Simulationen",
        fmt_int(overview["simulations_total"]),
        border=True,
    )
    overview_columns[1].metric(
        "Pfade",
        fmt_int(overview["paths_simulated"]),
        border=True,
    )
    overview_columns[2].metric(
        "Datensätze",
        fmt_int(overview["datasets_total"]),
        border=True,
    )
    overview_columns[3].metric(
        "Messungen",
        fmt_int(overview["measurements_total"]),
        border=True,
    )

simulation_tab, datasets_tab, history_tab = st.tabs(
    [
        ":material/play_circle: Simulation",
        ":material/database: Datensätze",
        ":material/history: Verlauf",
    ],
    on_change="rerun",
)

if simulation_tab.open:
    with simulation_tab:
        render_simulation_tab(api_url)

if datasets_tab.open:
    with datasets_tab:
        render_datasets_tab(api_url)

if history_tab.open:
    with history_tab:
        render_history_tab(api_url)

st.divider()
st.caption(
    "MonteCarlo Lab · API auf Render und Datenbank bei Neon · Code und Dokumentation im Repository."
)
