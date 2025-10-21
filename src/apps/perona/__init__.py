"""Perona - real-time VFX performance & cost dashboard."""

from .models import (  # noqa: F401
    CostEstimate,
    CostEstimateRequest,
    OptimizationBacktestRequest,
    OptimizationBacktestResponse,
    OptimizationResult,
    OptimizationScenarioRequest,
    PnLBreakdown,
    PnLContribution,
    RenderMetric,
    RiskIndicator,
    Sequence,
    Shot,
    ShotStage,
    shots_from_lifecycles,
    sequences_from_lifecycles,
)
from .version import PERONA_VERSION, __version__  # noqa: F401

__all__ = [
    "PERONA_VERSION",
    "__version__",
    "CostEstimate",
    "CostEstimateRequest",
    "OptimizationBacktestRequest",
    "OptimizationBacktestResponse",
    "OptimizationResult",
    "OptimizationScenarioRequest",
    "PnLBreakdown",
    "PnLContribution",
    "RenderMetric",
    "RiskIndicator",
    "Sequence",
    "Shot",
    "ShotStage",
    "shots_from_lifecycles",
    "sequences_from_lifecycles",
]
