"""Shared test setup."""
import pytest

import kalytera.analyzer as analyzer


@pytest.fixture(autouse=True)
def _no_model_calls_when_naming_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    """Naming a problem calls the judge model; tests never reach a real API (the .env key may be loaded)."""
    monkeypatch.setattr(analyzer, "_summarize_reasons", lambda reasons: None)
