"""Versioned recommendation model configuration and audit metadata."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config

MODEL_CONFIG_PATH = config.PROJECT_ROOT / "tefas.model.json"
DEFAULT_MODEL_VERSION = "tefas-reco-v2.1.0"

DEFAULT_OVERALL_WEIGHTS = {
    "sharpe": 0.25,
    "sortino": 0.15,
    "drawdown": 0.20,
    "return": 0.20,
    "theme_relative": 0.05,
    "consistency": 0.075,
    "liquidity": 0.075,
}

DEFAULT_PROFILE_WEIGHTS = {
    "Conservative": {"vol_low": 0.40, "dd_low": 0.30, "pos_days": 0.15, "consistency": 0.15},
    "Balanced": {"sortino": 0.30, "calmar": 0.25, "vol_band_mid": 0.20, "return": 0.15, "consistency": 0.10},
    "Moderate": {"sharpe": 0.40, "return": 0.25, "vol_band_mid": 0.20, "consistency": 0.15},
    "Aggressive": {"return": 0.40, "momentum": 0.25, "vol_pct": 0.15, "calmar": 0.10, "calmar_gate": 0.10},
}

DEFAULT_RECOMMENDATION_SETTINGS = {
    "theme_cap": 1,
    "exclude_young": True,
    "young_history_days": config.TRADING_DAYS_PER_YEAR,
}


@dataclass(frozen=True)
class ModelConfig:
    version: str = DEFAULT_MODEL_VERSION
    overall_weights: dict[str, float] = field(default_factory=lambda: DEFAULT_OVERALL_WEIGHTS.copy())
    profile_weights: dict[str, dict[str, float]] = field(
        default_factory=lambda: {k: v.copy() for k, v in DEFAULT_PROFILE_WEIGHTS.items()})
    recommendation_settings: dict[str, Any] = field(
        default_factory=lambda: DEFAULT_RECOMMENDATION_SETTINGS.copy())
    source: str = "defaults"


def _merge_weights(defaults: dict[str, float], raw: Any) -> dict[str, float]:
    out = defaults.copy()
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in out and isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = float(value)
    return out


def load(path: Path | None = None) -> ModelConfig:
    """Load optional model config; malformed/missing files fall back to defaults."""
    p = Path(path) if path is not None else MODEL_CONFIG_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except Exception:  # noqa: BLE001
        raw = {}

    version = raw.get("version") if isinstance(raw.get("version"), str) else DEFAULT_MODEL_VERSION
    overall = _merge_weights(DEFAULT_OVERALL_WEIGHTS, raw.get("overall_weights"))
    profiles = {
        name: _merge_weights(weights, (raw.get("profile_weights") or {}).get(name))
        for name, weights in DEFAULT_PROFILE_WEIGHTS.items()
    }
    settings = DEFAULT_RECOMMENDATION_SETTINGS.copy()
    if isinstance(raw.get("recommendation_settings"), dict):
        settings.update(raw["recommendation_settings"])
    return ModelConfig(
        version=version,
        overall_weights=overall,
        profile_weights=profiles,
        recommendation_settings=settings,
        source=str(p) if raw else "defaults",
    )


_MODEL: ModelConfig | None = None


def current() -> ModelConfig:
    global _MODEL
    if _MODEL is None:
        _MODEL = load()
    return _MODEL


def reset_cache() -> None:
    global _MODEL
    _MODEL = None
