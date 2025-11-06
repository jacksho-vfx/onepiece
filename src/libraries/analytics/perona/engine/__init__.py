"""Perona analytics engine package."""

from .engine import PeronaEngine
from .models import (
    CostBreakdown,
    CostModelInput,
    DEFAULT_CURRENCY,
    OptimizationResult,
    OptimizationScenario,
    PnLBreakdown,
    PnLContribution,
    RenderMetric,
    RiskIndicator,
    ShotLifecycle,
    ShotLifecycleStage,
    ShotTelemetry,
    SUPPORTED_CURRENCIES,
    get_currency_symbol,
)
from .settings import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_SETTINGS_PATH,
    DEFAULT_TARGET_ERROR_RATE,
    SettingsLoadResult,
)

__all__ = [
    "CostBreakdown",
    "CostModelInput",
    "DEFAULT_BASELINE_COST_INPUT",
    "DEFAULT_CURRENCY",
    "DEFAULT_PNL_BASELINE_COST",
    "DEFAULT_SETTINGS_PATH",
    "DEFAULT_TARGET_ERROR_RATE",
    "OptimizationResult",
    "OptimizationScenario",
    "PeronaEngine",
    "PnLBreakdown",
    "PnLContribution",
    "RenderMetric",
    "RiskIndicator",
    "SettingsLoadResult",
    "ShotLifecycle",
    "ShotLifecycleStage",
    "ShotTelemetry",
    "SUPPORTED_CURRENCIES",
    "get_currency_symbol",
]
