"""Smoke tests for the Streamlit app.

They exercise the real script with ``AppTest``; no API is required because the
app degrades gracefully when it cannot reach the backend.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_app_renders_without_api() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()

    assert not app.exception
    assert any("MonteCarlo Lab" in title.value for title in app.title)
    assert any("Neue Simulation" in subheader.value for subheader in app.subheader)


def test_switching_model_reshapes_the_form() -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    app.segmented_control[0].set_value("Normal").run()

    assert not app.exception
    labels = [item.label for item in app.number_input]
    assert "Mittelwert (μ)" in labels
    assert "Schritte" not in labels
