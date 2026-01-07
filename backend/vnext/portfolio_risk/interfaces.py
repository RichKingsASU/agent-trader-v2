from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")

if _PYDANTIC_V2:  # pragma: no cover
    from pydantic import ConfigDict  # type: ignore[attr-defined]


class ExposureSnapshot(BaseModel):
    """
    Read-only snapshot of portfolio exposures at a point in time.

    Notes:
    - Strategy-agnostic: consumers may compute exposures from any source (broker,
      ledger, backtest, or mock).
    - This model does not encode trading intent; it is descriptive only.
    """

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid", frozen=True)
    else:  # pragma: no cover
        class Config:
            extra = "forbid"
            allow_mutation = False

    as_of_utc: datetime = Field(..., description="UTC timestamp of the exposure snapshot")
    base_currency: str = Field(default="USD", min_length=3, description="Reporting currency (ISO-like)")

    # Optional totals (implementations may omit if unknown).
    total_value_usd: Optional[float] = Field(default=None, description="Portfolio total value in USD")
    net_exposure_usd: Optional[float] = Field(default=None, description="Net exposure in USD (signed)")
    gross_exposure_usd: Optional[float] = Field(default=None, description="Gross exposure in USD (abs-sum)")

    # Common, lightweight breakdowns (implementations can choose which to populate).
    exposures_usd_by_symbol: Dict[str, float] = Field(
        default_factory=dict,
        description="Signed USD exposure keyed by symbol (e.g., {'SPY': 12000.0, 'AAPL': -5000.0})",
    )
    exposures_usd_by_asset_class: Dict[str, float] = Field(
        default_factory=dict,
        description="Signed USD exposure keyed by asset class (e.g., {'EQUITY': 10000.0, 'OPTION': 2000.0})",
    )

    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Implementation-defined metadata (e.g., pricing source, accounting basis)",
    )


class ConcentrationMetric(BaseModel):
    """
    Generic concentration metric for a portfolio, computed over some dimension.

    Examples:
    - metric='top_n_weight', dimension='symbol', value=0.42, params={'n': 5}
    - metric='hhi', dimension='sector', value=0.09
    """

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid", frozen=True)
    else:  # pragma: no cover
        class Config:
            extra = "forbid"
            allow_mutation = False

    as_of_utc: datetime = Field(..., description="UTC timestamp the metric applies to")
    metric: str = Field(..., min_length=1, description="Metric name (e.g., 'hhi', 'top_n_weight')")
    dimension: str = Field(
        ...,
        min_length=1,
        description="Dimension aggregated over (e.g., 'symbol', 'sector', 'issuer', 'asset_class')",
    )
    value: float = Field(..., description="Metric value (unit depends on metric)")

    top_keys: List[str] = Field(
        default_factory=list,
        description="Optional: keys that most influenced the concentration (ordered highest impact first)",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional: metric parameters (e.g., {'n': 10} for top-n metrics)",
    )


class CorrelatedPair(BaseModel):
    """A single pairwise correlation observation."""

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid", frozen=True)
    else:  # pragma: no cover
        class Config:
            extra = "forbid"
            allow_mutation = False

    a: str = Field(..., min_length=1, description="First symbol/key")
    b: str = Field(..., min_length=1, description="Second symbol/key")
    correlation: float = Field(..., ge=-1.0, le=1.0, description="Correlation in [-1, 1]")


class CorrelationRisk(BaseModel):
    """
    Correlation/diversification risk summary.

    Notes:
    - Intended to describe portfolio diversification, not to prescribe trades.
    - Correlations can be computed on symbols, factors, sectors, or any other keys.
    """

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid", frozen=True)
    else:  # pragma: no cover
        class Config:
            extra = "forbid"
            allow_mutation = False

    as_of_utc: datetime = Field(..., description="UTC timestamp the risk summary applies to")
    lookback_days: int = Field(default=60, gt=0, description="Historical window length used for correlation estimates")
    method: str = Field(default="pearson", min_length=1, description="Correlation estimator (e.g., 'pearson')")
    frequency: str = Field(default="1d", min_length=1, description="Sampling frequency (e.g., '1d', '1h')")

    average_pairwise_correlation: Optional[float] = Field(
        default=None, ge=-1.0, le=1.0, description="Average pairwise correlation across keys (if computed)"
    )
    max_pairwise_correlation: Optional[float] = Field(
        default=None, ge=-1.0, le=1.0, description="Maximum observed pairwise correlation (if computed)"
    )
    min_pairwise_correlation: Optional[float] = Field(
        default=None, ge=-1.0, le=1.0, description="Minimum observed pairwise correlation (if computed)"
    )

    most_correlated: Optional[CorrelatedPair] = Field(
        default=None, description="Optional: the most positively correlated pair"
    )
    least_correlated: Optional[CorrelatedPair] = Field(
        default=None, description="Optional: the most negatively correlated pair"
    )
    top_pairs: List[CorrelatedPair] = Field(
        default_factory=list,
        description="Optional: ranked list of noteworthy correlation pairs (implementation-defined ranking)",
    )

    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Implementation-defined metadata (e.g., data sources, missing data stats)",
    )


class PortfolioRiskReport(BaseModel):
    """Container for portfolio-level risk outputs (read-only)."""

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid", frozen=True)
    else:  # pragma: no cover
        class Config:
            extra = "forbid"
            allow_mutation = False

    exposure: ExposureSnapshot
    concentration: List[ConcentrationMetric] = Field(default_factory=list)
    correlation: Optional[CorrelationRisk] = None


class PortfolioRiskProvider(ABC):
    """
    Read-only interface for computing portfolio-level risk aggregation.

    This is intentionally strategy-agnostic and does not include any execution or
    trading capability.
    """

    @abstractmethod
    def get_portfolio_risk(self, *, as_of_utc: Optional[datetime] = None) -> PortfolioRiskReport: ...

