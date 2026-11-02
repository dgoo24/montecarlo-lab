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
    "pending": "Pendiente",
    "running": "En ejecución",
    "completed": "Completada",
    "failed": "Fallida",
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
            "Movimiento browniano geométrico: crecimiento multiplicativo con "
            "volatilidad constante. El modelo clásico para precios de activos."
        ),
    },
    "Ornstein-Uhlenbeck": {
        "kind": "ou",
        "description": (
            "Proceso con reversión a la media: la serie es atraída hacia μ a una "
            "velocidad θ. Útil para magnitudes físicas que vuelven a su equilibrio."
        ),
    },
    "Normal": {
        "kind": "normal",
        "description": (
            "Propagación estática de incertidumbre: una extracción N(μ, σ²) por "
            "trayectoria, sin dimensión temporal."
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
                message = str(item.get("msg", "valor inválido"))
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
            f"No se pudo conectar con la API en {base_url}. "
            "Comprueba que el servicio está arrancado."
        ) from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        detail = payload.get("detail") if isinstance(payload, dict) else None
        message = _error_detail(detail) if detail else f"Error HTTP {response.status_code}"
        raise ApiError(message, status_code=response.status_code, detail=detail)

    if response.status_code == 204:
        return None
    return response.json()


def render_api_error(error: ApiError) -> None:
    st.error(str(error))
    if error.detail and not isinstance(error.detail, str):
        with st.expander("Detalle del error", icon=":material/bug_report:"):
            st.json(error.detail)


# ---------------------------------------------------------------------------
# Cached API loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=15, show_spinner="Conectando con la API…")
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


def fmt_number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.6g}"


def fmt_metric(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.6g}"


def fmt_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC")
        return stamp.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return value


def fmt_duration(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,} ms"


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
        f"semilla {run['seed'] if run['seed'] is not None else 'aleatoria'} · "
        f"{fmt_datetime(run['created_at'])}"
    )

    if status != "completed":
        if status == "failed":
            st.error(run.get("error") or "La ejecución falló sin mensaje de error.")
        else:
            st.info(
                "La simulación todavía no tiene resultados. "
                f"Estado actual: {STATUS_LABELS.get(status, status)}."
            )
        return

    summary = run.get("summary") or {}
    threshold = run.get("threshold")

    metric_columns = st.columns(5)
    metric_columns[0].metric("Media", fmt_metric(summary.get("mean")), border=True)
    metric_columns[1].metric("Desv. típica", fmt_metric(summary.get("std")), border=True)
    metric_columns[2].metric("P05", fmt_metric(summary.get("p05")), border=True)
    metric_columns[3].metric("Mediana", fmt_metric(summary.get("p50")), border=True)
    metric_columns[4].metric("P95", fmt_metric(summary.get("p95")), border=True)

    chart_column, series_column = st.columns(2, gap="large")

    with chart_column:
        with st.container(border=True):
            st.markdown("**Distribución de valores terminales**")
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
                    f"{start:,.4g} – {end:,.4g}"
                    for start, end in zip(hist_frame["start"], hist_frame["end"], strict=True)
                ]

                bars = (
                    alt.Chart(hist_frame)
                    .mark_bar(color=PRIMARY)
                    .encode(
                        x=alt.X("start:Q", title="Valor terminal"),
                        x2="end:Q",
                        y=alt.Y("count:Q", title="Trayectorias"),
                        tooltip=[
                            alt.Tooltip("interval:N", title="Intervalo"),
                            alt.Tooltip("count:Q", title="Trayectorias", format=","),
                        ],
                    )
                )
                mean_rule = (
                    alt.Chart(pd.DataFrame({"x": [summary["mean"]]}))
                    .mark_rule(color=ACCENT, strokeDash=[5, 3], strokeWidth=1.6)
                    .encode(x="x:Q")
                )
                layers: list[alt.Chart] = [bars, mean_rule]
                caption = "Línea ámbar discontinua: media."

                if threshold is not None:
                    threshold_rule = (
                        alt.Chart(pd.DataFrame({"x": [threshold]}))
                        .mark_rule(color=DANGER, strokeDash=[2, 3], strokeWidth=1.4)
                        .encode(x="x:Q")
                    )
                    layers.append(threshold_rule)
                    caption = "Línea ámbar discontinua: media · línea roja: umbral."

                chart = style_chart(alt.layer(*layers).properties(height=300))
                st.altair_chart(
                    chart,
                    alt=(
                        f"Histograma de {summary['mean']:.4g} valores terminales medios "
                        f"repartidos en {len(histogram['counts'])} intervalos"
                    ),
                )
                st.caption(caption)

    with series_column:
        with st.container(border=True):
            st.markdown("**Trayectorias simuladas**")
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
                            x=alt.X("value:Q", title="Valor"),
                            y=alt.Y("path:O", title=None, axis=None),
                            tooltip=[
                                alt.Tooltip("path:N", title="Trayectoria"),
                                alt.Tooltip("value:Q", title="Valor", format=",.4f"),
                            ],
                        )
                        .properties(height=300)
                    )
                    st.altair_chart(
                        chart,
                        alt=(
                            "Muestras del modelo Normal: una extracción por trayectoria "
                            "en un eje horizontal"
                        ),
                    )
                    st.caption(
                        "El modelo Normal no tiene dimensión temporal; "
                        "cada trayectoria es una única extracción."
                    )
                else:
                    dt = trajectories.get("dt") or 1.0
                    time_label = "Tiempo (años)" if dt != 1.0 else "Paso"
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
                                title="Valor",
                                scale=alt.Scale(zero=False),
                            ),
                            detail="path:N",
                            tooltip=[
                                alt.Tooltip("path:N", title="Trayectoria"),
                                alt.Tooltip("step:Q", title="Paso"),
                                alt.Tooltip("value:Q", title="Valor", format=",.4f"),
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
                            f"{len(paths)} trayectorias de valores a lo largo de "
                            f"{len(steps)} puntos temporales, con su media en ámbar"
                        ),
                    )
                    st.caption(
                        f"{len(paths)} trayectorias de {trajectories['total_paths']:,} "
                        "muestreadas · línea ámbar: media."
                    )

    st.write("")
    stats_column, details_column = st.columns([3, 2], gap="large")

    with stats_column:
        with st.container(border=True):
            st.markdown("**Estadísticos de los valores terminales**")
            stats_rows: list[tuple[str, str]] = [
                ("Media", fmt_number(summary.get("mean"))),
                ("Desviación típica", fmt_number(summary.get("std"))),
                ("Mínimo", fmt_number(summary.get("minimum"))),
                ("P05", fmt_number(summary.get("p05"))),
                ("P25", fmt_number(summary.get("p25"))),
                ("Mediana (P50)", fmt_number(summary.get("p50"))),
                ("P75", fmt_number(summary.get("p75"))),
                ("P95", fmt_number(summary.get("p95"))),
                ("Máximo", fmt_number(summary.get("maximum"))),
                ("VaR 95 % (P05)", fmt_number(summary.get("var_95"))),
                (
                    "Expected shortfall 95 %",
                    fmt_number(summary.get("expected_shortfall_95")),
                ),
            ]
            if summary.get("prob_above_threshold") is not None:
                stats_rows.append(
                    (
                        "P(X > umbral)",
                        f"{summary['prob_above_threshold']:.2%}",
                    )
                )

            st.dataframe(
                pd.DataFrame(stats_rows, columns=["Métrica", "Valor"]),
                hide_index=True,
                height="content",
                alt="Tabla de estadísticos de la simulación",
            )

    with details_column:
        with st.container(border=True):
            st.markdown("**Ejecución**")
            details_rows = [
                ("Modelo", run["model"].upper()),
                ("Trayectorias", f"{run['n_paths']:,}"),
                ("Pasos", f"{run['n_steps']:,}"),
                (
                    "Semilla",
                    f"{run['seed']:,}" if run["seed"] is not None else "aleatoria",
                ),
                ("Umbral", fmt_number(threshold)),
                ("Duración", fmt_duration(run.get("duration_ms"))),
                ("Finalizada", fmt_datetime(run.get("finished_at"))),
            ]
            st.dataframe(
                pd.DataFrame(details_rows, columns=["Campo", "Valor"]),
                hide_index=True,
                height="content",
                alt="Tabla con los parámetros de ejecución",
            )

    with st.expander("Parámetros y respuesta JSON", icon=":material/data_object:"):
        st.json(run)


# ---------------------------------------------------------------------------
# Simulation tab
# ---------------------------------------------------------------------------


def render_simulation_tab(api_url: str) -> None:
    st.subheader("Nueva simulación")
    st.caption(
        "Los parámetros se validan en la API. Cada ejecución se guarda en PostgreSQL "
        "y es reproducible con su semilla."
    )

    model_label = (
        st.segmented_control(
            "Modelo estocástico",
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
            "Nombre de la simulación",
            placeholder=f"{model_label} · 1.000 trayectorias",
            max_chars=200,
            key="simulation_name",
        )

        st.markdown("**Parámetros del modelo**")
        if model["kind"] == "gbm":
            parameter_columns = st.columns(4)
            s0 = parameter_columns[0].number_input(
                "Valor inicial (S₀)",
                min_value=0.01,
                value=100.0,
                step=1.0,
                help="Precio o magnitud de partida. Debe ser mayor que 0.",
                key="gbm_s0",
            )
            mu = parameter_columns[1].number_input(
                "Deriva anual (μ)",
                value=0.08,
                step=0.01,
                format="%.4f",
                help="Tasa de crecimiento esperada por año.",
                key="gbm_mu",
            )
            sigma = parameter_columns[2].number_input(
                "Volatilidad anual (σ)",
                min_value=0.001,
                max_value=5.0,
                value=0.20,
                step=0.01,
                format="%.4f",
                help="Volatilidad anual. Debe ser mayor que 0 y como máximo 5.",
                key="gbm_sigma",
            )
            dt = parameter_columns[3].number_input(
                "Paso temporal (dt)",
                min_value=0.0001,
                max_value=1.0,
                value=1 / 252,
                step=0.0001,
                format="%.6f",
                help="Fracción de año entre puntos. 1/252 equivale a un día bursátil.",
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
                "Valor inicial (x₀)",
                value=0.0,
                step=1.0,
                format="%.4f",
                help="Valor de la serie en el instante inicial.",
                key="ou_x0",
            )
            mu = parameter_columns[1].number_input(
                "Media de largo plazo (μ)",
                value=0.0,
                step=1.0,
                format="%.4f",
                help="Nivel al que el proceso tiende a volver.",
                key="ou_mu",
            )
            theta = parameter_columns[2].number_input(
                "Reversión (θ)",
                min_value=0.0001,
                value=1.5,
                step=0.1,
                format="%.4f",
                help="Velocidad de reversión a la media. Debe ser mayor que 0.",
                key="ou_theta",
            )
            sigma = parameter_columns[3].number_input(
                "Volatilidad (σ)",
                min_value=0.0001,
                max_value=100.0,
                value=0.30,
                step=0.05,
                format="%.4f",
                help="Intensidad del ruido. Debe ser mayor que 0.",
                key="ou_sigma",
            )
            dt = parameter_columns[4].number_input(
                "Paso temporal (dt)",
                min_value=0.0001,
                max_value=1.0,
                value=1 / 252,
                step=0.0001,
                format="%.6f",
                help="Fracción de año entre puntos.",
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
                "Media (μ)",
                value=100.0,
                step=1.0,
                format="%.4f",
                help="Centro de la distribución normal.",
                key="normal_mean",
            )
            std = parameter_columns[1].number_input(
                "Desviación típica (σ)",
                min_value=0.0001,
                value=15.0,
                step=1.0,
                format="%.4f",
                help="Dispersión de la distribución. Debe ser mayor que 0.",
                key="normal_std",
            )
            params = {"kind": "normal", "mean": mean, "std": std}
            n_steps_default = 1
            show_steps = False

        st.divider()
        st.markdown("**Carga de trabajo**")
        workload_columns = st.columns(4 if show_steps else 3)
        n_paths = workload_columns[0].number_input(
            "Trayectorias",
            min_value=100,
            max_value=MAX_PATHS,
            value=1_000,
            step=100,
            help="Número de caminos a simular. La API acepta entre 100 y 20.000.",
            key="n_paths",
        )
        if show_steps:
            n_steps = workload_columns[1].number_input(
                "Pasos",
                min_value=1,
                max_value=MAX_STEPS,
                value=n_steps_default,
                step=1,
                help="Puntos por trayectoria. La API acepta como máximo 5.000.",
                key="n_steps",
            )
            seed_column = workload_columns[2]
            threshold_column = workload_columns[3]
        else:
            n_steps = 1
            seed_column = workload_columns[1]
            threshold_column = workload_columns[2]

        seed = seed_column.number_input(
            "Semilla",
            min_value=0,
            max_value=2**53 - 1,
            value=42,
            step=1,
            help="Misma semilla y mismos parámetros producen exactamente el mismo resultado.",
            key="seed",
        )
        threshold = threshold_column.number_input(
            "Umbral (opcional)",
            value=None,
            step=1.0,
            format="%.4f",
            placeholder="Sin umbral",
            help="Si se indica, la API calcula P(X > umbral).",
            key="threshold",
        )

        submitted = st.form_submit_button(
            "Ejecutar simulación",
            type="primary",
            icon=":material/play_arrow:",
        )

    st.caption(
        f"Límites de la instancia: {MAX_PATHS:,} trayectorias, {MAX_STEPS:,} pasos "
        f"y {MAX_CELLS:,} celdas (trayectorias × pasos) por ejecución."
    )

    if submitted:
        if n_paths * n_steps > MAX_CELLS:
            st.error(
                f"La carga solicitada ({n_paths * n_steps:,} celdas) supera el límite "
                f"de {MAX_CELLS:,}. Reduce el número de trayectorias o de pasos."
            )
        else:
            payload = {
                "name": name.strip() or f"{model_label} · {n_paths:,} trayectorias",
                "params": params,
                "n_paths": int(n_paths),
                "n_steps": int(n_steps),
                "seed": int(seed),
                "threshold": threshold,
            }

            status_box = st.status("Ejecutando la simulación…", expanded=False)
            try:
                run = api_request(
                    api_url,
                    "POST",
                    f"{API_PREFIX}/simulations",
                    json=payload,
                )
            except ApiError as exc:
                status_box.update(
                    label="No se pudo ejecutar la simulación",
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
                            f"Simulación completada en {run['duration_ms']:,} ms · "
                            f"{run['n_paths']:,} trayectorias"
                        ),
                        state="complete",
                    )
                else:
                    status_box.update(
                        label=(
                            "La simulación terminó con estado "
                            f"{STATUS_LABELS.get(run['status'], run['status']).lower()}"
                        ),
                        state="error",
                        expanded=True,
                    )
                    st.error(run.get("error") or "La simulación no produjo resultados.")

    last_run_id = st.session_state.get("last_run_id")
    if last_run_id:
        st.divider()
        st.subheader("Resultados")
        render_simulation_results(api_url, last_run_id)
    else:
        st.info(
            "Configura los parámetros y pulsa **Ejecutar simulación** para ver el "
            "histograma, las trayectorias y los estadísticos."
        )


# ---------------------------------------------------------------------------
# Datasets tab
# ---------------------------------------------------------------------------


def render_dataset_upload(api_url: str) -> None:
    with st.form("dataset_upload_form", border=True, clear_on_submit=True):
        st.markdown("**Subir un CSV**")
        upload_columns = st.columns([2, 2, 1, 1])
        uploaded_file = upload_columns[0].file_uploader(
            "Archivo CSV",
            type=["csv"],
            help="Máximo 10 MB. Se detectan codificación, separador y cabecera.",
        )
        dataset_name = upload_columns[1].text_input(
            "Nombre del dataset",
            placeholder="Medidas del reactor",
            max_chars=200,
        )
        default_variable = upload_columns[2].text_input(
            "Variable por defecto",
            value="value",
            max_chars=80,
            help="Se usa cuando el CSV no trae una columna 'variable'.",
        )
        default_unit = upload_columns[3].text_input(
            "Unidad por defecto",
            max_chars=32,
            placeholder="bar",
        )

        with st.expander("Opciones avanzadas de columnas", icon=":material/tune:"):
            advanced_columns = st.columns(2)
            timestamp_column = advanced_columns[0].text_input(
                "Columna de tiempo",
                value="timestamp",
                max_chars=80,
            )
            value_column = advanced_columns[1].text_input(
                "Columna de valor",
                value="value",
                max_chars=80,
            )

        upload_submitted = st.form_submit_button(
            "Procesar y guardar",
            type="primary",
            icon=":material/upload:",
        )

    if upload_submitted:
        if uploaded_file is None:
            st.warning("Selecciona un archivo CSV antes de enviarlo.")
        else:
            form_data = {
                "name": dataset_name.strip() or uploaded_file.name,
                "variable": default_variable.strip() or "value",
                "timestamp_column": timestamp_column.strip() or "timestamp",
                "value_column": value_column.strip() or "value",
            }
            if default_unit.strip():
                form_data["unit"] = default_unit.strip()

            status_box = st.status("Procesando el CSV con Pandas…", expanded=False)
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
                status_box.update(label="El CSV no se pudo procesar", state="error", expanded=True)
                render_api_error(exc)
            else:
                st.session_state["dataset_choice"] = dataset["id"]
                refresh_dataset_caches()
                status_box.update(
                    label=(
                        f"Dataset guardado · {dataset['row_count']:,} medidas · "
                        f"{dataset['outlier_rows']:,} outliers marcados"
                    ),
                    state="complete",
                )
                if dataset.get("rejected_rows"):
                    st.warning(
                        f"{dataset['rejected_rows']:,} filas se rechazaron por timestamps "
                        "o valores inválidos. Revisa el detalle en la ficha ETL."
                    )

    sample_path = Path(__file__).resolve().parent.parent / "data" / "sample_measurements.csv"
    if sample_path.exists():
        st.download_button(
            "Descargar CSV de ejemplo",
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
        f"subido el {fmt_datetime(dataset['created_at'])} · "
        f"sha256 `{dataset['checksum_sha256'][:12]}…`"
    )

    if dataset.get("status") == "failed":
        st.error(dataset.get("error") or "El ETL falló al procesar este dataset.")

    metric_columns = st.columns(4)
    metric_columns[0].metric("Medidas", f"{stats['row_count']:,}", border=True)
    metric_columns[1].metric("Filas rechazadas", f"{stats['rejected_rows']:,}", border=True)
    metric_columns[2].metric("Outliers (IQR)", f"{stats['outlier_rows']:,}", border=True)
    metric_columns[3].metric("Variables", f"{len(stats['variables']):,}", border=True)

    if not stats["variables"]:
        st.info("Este dataset no contiene variables válidas.")
        return

    variables_frame = pd.DataFrame(stats["variables"]).rename(
        columns={
            "variable": "Variable",
            "count": "Medidas",
            "mean": "Media",
            "std": "Desv. típica",
            "minimum": "Mínimo",
            "maximum": "Máximo",
            "outliers": "Outliers",
        }
    )
    st.dataframe(
        variables_frame,
        hide_index=True,
        height="content",
        alt="Estadísticos por variable del dataset",
    )

    variable_names = [item["variable"] for item in stats["variables"]]
    variable_column, _ = st.columns([2, 3])
    selected_variable = variable_column.selectbox(
        "Variable para la serie temporal",
        options=variable_names,
        key=f"dataset_variable_{dataset['id']}",
    )

    try:
        frame, total, fetched = load_measurements(api_url, dataset["id"], selected_variable)
    except ApiError as exc:
        render_api_error(exc)
        return

    if frame.empty:
        st.info("No hay medidas disponibles para esta variable.")
        return

    with st.container(border=True):
        st.markdown(f"**Serie temporal · {selected_variable}**")
        unit = frame["unit"].dropna().iloc[0] if frame["unit"].notna().any() else None
        y_title = f"{selected_variable} ({unit})" if unit else selected_variable

        line = (
            alt.Chart(frame)
            .mark_line(color=PRIMARY, strokeWidth=1.4)
            .encode(
                x=alt.X("recorded_at:T", title=None),
                y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=False)),
                tooltip=[
                    alt.Tooltip("recorded_at:T", title="Fecha", format="%Y-%m-%d %H:%M"),
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
                        alt.Tooltip("recorded_at:T", title="Fecha", format="%Y-%m-%d %H:%M"),
                        alt.Tooltip("value:Q", title="Valor atípico", format=",.4f"),
                    ],
                )
            )
            layers.append(outlier_points)

        chart = style_chart(alt.layer(*layers).properties(height=320).interactive())
        st.altair_chart(
            chart,
            alt=(
                f"Serie temporal de {selected_variable} con {len(outliers)} "
                "valores atípicos resaltados en rojo"
            ),
        )
        st.caption(f"{fetched:,} de {total:,} medidas · puntos rojos: outliers detectados con IQR.")

    with st.container(horizontal=True, horizontal_alignment="right"):
        st.download_button(
            "Descargar medidas (CSV)",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=f"{dataset['name'][:40].replace(' ', '_')}_{selected_variable}.csv",
            mime="text/csv",
            icon=":material/download:",
            type="tertiary",
        )

    with st.expander(f"Ver medidas ({fetched:,})", icon=":material/table_rows:"):
        display_frame = frame.head(500).rename(
            columns={
                "recorded_at": "Fecha",
                "variable": "Variable",
                "value": "Valor",
                "unit": "Unidad",
                "is_outlier": "Outlier",
            }
        )
        st.dataframe(
            display_frame[["Fecha", "Variable", "Valor", "Unidad", "Outlier"]],
            hide_index=True,
            height=280,
            alt="Tabla de medidas del dataset",
        )

    with st.expander("Ficha ETL del dataset", icon=":material/fact_check:"):
        st.json(dataset)
        st.json(stats)


def render_datasets_tab(api_url: str) -> None:
    st.subheader("Datasets experimentales")
    st.caption(
        "El ETL de Pandas valida tipos, elimina duplicados, marca outliers con el "
        "rango intercuartílico (IQR) y registra un checksum SHA-256 del archivo."
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
        st.info("Todavía no hay datasets. Sube un CSV o usa el archivo de ejemplo.")
        return

    by_id = {item["id"]: item for item in items}
    options = list(by_id)
    default_id = st.session_state.get("dataset_choice")
    if default_id not in options:
        default_id = options[0]

    selected_id = st.selectbox(
        "Dataset",
        options=options,
        index=options.index(default_id),
        format_func=lambda dataset_id: (
            f"{by_id[dataset_id]['name']} · {by_id[dataset_id]['row_count']:,} medidas · "
            f"{fmt_datetime(by_id[dataset_id]['created_at'])}"
        ),
        key="dataset_choice",
    )
    st.divider()
    render_dataset_details(api_url, by_id[selected_id])


# ---------------------------------------------------------------------------
# History tab
# ---------------------------------------------------------------------------


def render_history_tab(api_url: str) -> None:
    st.subheader("Historial de ejecuciones")
    st.caption("Cada ejecución conserva sus parámetros, su semilla y sus resultados en PostgreSQL.")

    filter_label = st.segmented_control(
        "Filtrar por estado",
        options=["Todas", "Completadas", "Fallidas"],
        default="Todas",
        key="history_status",
    )
    status_lookup = {"Todas": None, "Completadas": "completed", "Fallidas": "failed"}
    run_status = status_lookup.get(filter_label or "Todas")

    try:
        runs = load_runs(api_url, run_status)
    except ApiError as exc:
        render_api_error(exc)
        return

    items = runs["items"]
    if not items:
        st.info("No hay ejecuciones que coincidan con el filtro.")
        return

    completed = sum(1 for item in items if item["status"] == "completed")
    failed = sum(1 for item in items if item["status"] == "failed")
    metric_columns = st.columns(3)
    metric_columns[0].metric("Ejecuciones", f"{runs['total']:,}", border=True)
    metric_columns[1].metric("Completadas", f"{completed:,}", border=True)
    metric_columns[2].metric("Fallidas", f"{failed:,}", border=True)

    table_rows = []
    for item in items:
        summary = item.get("summary") or {}
        table_rows.append(
            {
                "Fecha": fmt_datetime(item["created_at"]).replace(" UTC", ""),
                "Nombre": item["name"],
                "Modelo": item["model"].upper(),
                "Estado": STATUS_LABELS.get(item["status"], item["status"]),
                "Trayectorias": item["n_paths"],
                "Pasos": item["n_steps"],
                "Media": fmt_number(summary.get("mean")),
                "Duración": fmt_duration(item.get("duration_ms")),
            }
        )

    st.dataframe(
        pd.DataFrame(table_rows),
        hide_index=True,
        height="content",
        alt="Tabla con el historial de simulaciones",
    )

    by_id = {item["id"]: item for item in items}
    options = list(by_id)
    default_id = st.session_state.get("history_run")
    if default_id not in options:
        default_id = options[0]

    selected_id = st.selectbox(
        "Abrir una ejecución",
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
            "URL de la API",
            value=default_api_url(),
            help="Local: http://localhost:8000 · Producción: la URL de Render.",
        )
        or DEFAULT_API_URL
    ).rstrip("/")

    api_status = load_api_status(api_url)
    if api_status["error"]:
        st.badge("API no disponible", color="red", icon=":material/cloud_off:")
        with st.expander("Detalle de la conexión", icon=":material/error:"):
            st.caption(api_status["error"])
    else:
        st.badge("API y base de datos operativas", color="green", icon=":material/check_circle:")
        health = api_status["health"]
        st.caption(f"Versión {health['version']} · entorno `{health['environment']}`")

    with st.container(horizontal=True):
        if st.button("Reintentar", icon=":material/refresh:", type="tertiary"):
            load_api_status.clear()
            st.rerun()
        st.link_button(
            "OpenAPI",
            f"{api_url}/docs",
            icon=":material/menu_book:",
            type="tertiary",
        )

    st.divider()
    st.markdown("**Límites por ejecución**")
    st.caption(
        f"{MAX_PATHS:,} trayectorias · {MAX_STEPS:,} pasos · "
        f"{MAX_CELLS:,} celdas. Las ejecuciones son síncronas y quedan persistidas."
    )
    st.divider()
    st.caption(
        "Proyecto de portafolio backend: API REST, motor Monte Carlo con NumPy, "
        "ETL con Pandas y persistencia en PostgreSQL."
    )

st.title(":material/science: MonteCarlo Lab")
st.caption(
    "Simula procesos estocásticos, explora su distribución y analiza medidas "
    "experimentales. Todos los resultados quedan guardados en PostgreSQL."
)

overview = load_overview(api_url) if not api_status["error"] else None
if overview:
    overview_columns = st.columns(4)
    overview_columns[0].metric(
        "Simulaciones",
        f"{overview['simulations_total']:,}",
        border=True,
    )
    overview_columns[1].metric(
        "Trayectorias",
        f"{overview['paths_simulated']:,}",
        border=True,
    )
    overview_columns[2].metric(
        "Datasets",
        f"{overview['datasets_total']:,}",
        border=True,
    )
    overview_columns[3].metric(
        "Medidas",
        f"{overview['measurements_total']:,}",
        border=True,
    )

simulation_tab, datasets_tab, history_tab = st.tabs(
    [
        ":material/play_circle: Simulación",
        ":material/database: Datasets",
        ":material/history: Historial",
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
    "MonteCarlo Lab · API desplegable en Render y base de datos en Neon · "
    "código y documentación en el repositorio."
)
