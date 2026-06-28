"""
Central configuration: tradable universe, strategy parameters, risk limits,
and credential loading. Keys are read from the environment (.env), never hardcoded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()  # loads .env if present; safe no-op otherwise


# ─── Credentials (loaded from environment — never hardcode) ──────────────
@dataclass(frozen=True)
class AlpacaCredentials:
    api_key: str
    secret_key: str
    base_url: str
    is_paper: bool

    @classmethod
    def from_env(cls) -> "AlpacaCredentials":
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        is_paper = "paper" in base_url.lower()
        if not api_key or not secret_key:
            raise RuntimeError(
                "Missing Alpaca keys. Copy .env.example to .env and fill in your "
                "PAPER keys (ALPACA_API_KEY / ALPACA_SECRET_KEY)."
            )
        return cls(api_key=api_key, secret_key=secret_key, base_url=base_url, is_paper=is_paper)


# ─── Universe ────────────────────────────────────────────────────────────
# Sleeve A: Time-Series Momentum on broad, liquid, cross-asset ETFs.
# Cross-asset by design so the trend sleeve can be long bonds/gold when
# equities are falling (the 2008-style crash hedge).
# Original v1 cross-asset sleeve (kept for reference / one-line revert). Research
# (PLAN §2F) found this 6-ETF set is the most *consistent* across both halves.
TSMOM_UNIVERSE_CORE6: List[str] = ["SPY", "QQQ", "IWM", "TLT", "GLD", "EFA"]

# Active TSMOM universe: the maximally-independent ETF set (|corr|<0.70, n=10),
# selected on in-sample data by research/independent_universe.py. NOTE: its strong
# out-of-sample Sharpe is partly a 2019-26 regime effect (in-sample is weaker) —
# revert to TSMOM_UNIVERSE_CORE6 if you want the more consistent universe.
TSMOM_UNIVERSE: List[str] = [
    "QQQ",                     # US equity (sole equity representative)
    "GLD", "USO", "DBA",       # commodities: gold, oil, agriculture
    "LQD", "HYG", "SHY", "EMB",  # credit / short govt / EM bonds
    "VNQ",                     # real estate
    "UUP",                     # US dollar
]

# Broadened cross-asset universe (research lever "a"): ~18 liquid ETFs across
# equities (US/intl/EM), the full bond curve, commodities, and real estate. More
# low-correlation instruments is the main driver of time-series-momentum Sharpe
# (Moskowitz/Ooi/Pedersen used 58 futures across 4 asset classes). All have
# history back to ≤2010 so the 2011-start backtest is clean.
TSMOM_UNIVERSE_BROAD: List[str] = [
    "SPY", "QQQ", "IWM",                 # US equity
    "EFA", "EEM", "VGK", "EWJ",          # intl / EM / Europe / Japan equity
    "TLT", "IEF", "SHY", "LQD", "HYG", "TIP", "EMB",  # bonds: govt curve, IG, HY, TIPS, EM
    "GLD", "SLV", "DBC",                 # commodities: gold, silver, broad
    "VNQ",                               # real estate
]

# Sleeve B: Cross-Sectional (sector rotation) — the 11 SPDR sectors.
SECTOR_UNIVERSE: List[str] = [
    "XLK",  # technology
    "XLF",  # financials
    "XLE",  # energy
    "XLV",  # health care
    "XLI",  # industrials
    "XLY",  # consumer discretionary
    "XLP",  # consumer staples
    "XLU",  # utilities
    "XLB",  # materials
    "XLRE", # real estate
    "XLC",  # communication services
]

BENCHMARK: str = "SPY"

# ─── Deployed strategy: core-satellite ───────────────────────────────────
# The deployed algorithm is 50% always-on equity beta (SPY) + 50% the
# diversifying momentum blend. Adding the equity core captures the bull market
# the bare blend missed and raised both the Sharpe and its in-sample/out-of-sample
# consistency (PLAN §2K). The SPY core is exempt from the per-name cap.
CORE_EQUITY_SYMBOL: str = "SPY"
CORE_EQUITY_WEIGHT: float = 0.5


# ─── Strategy parameters ─────────────────────────────────────────────────
@dataclass(frozen=True)
class StrategyParams:
    # Time-Series Momentum (Moskowitz/Ooi/Pedersen): 12-month lookback, 1-month hold.
    tsmom_lookback_months: int = 12
    tsmom_skip_months: int = 0          # 0 = use full 12m; some variants skip most recent month

    # Cross-Sectional momentum: 12-1 (12m lookback, skip most recent 1m), hold top N.
    xsec_lookback_months: int = 12
    xsec_skip_months: int = 1
    xsec_top_n: int = 3

    # Volatility-targeting overlay (conservative — see PLAN.md caveat).
    target_annual_vol: float = 0.10     # 10% annualized portfolio vol target
    vol_lookback_days: int = 60         # realized-vol estimation window
    max_leverage: float = 1.0           # NEVER lever up; only de-risk

    # Sleeve blend (must sum to 1.0).
    weight_tsmom: float = 0.5
    weight_xsec: float = 0.5

    # ── Research levers (defaults reproduce the v1 long/flat equal-weight sleeve) ──
    tsmom_allow_short: bool = False     # (b) short negative-momentum assets vs. go to cash
    tsmom_risk_scaled: bool = False     # (c) inverse-vol (equal-risk) sizing vs. equal weight

    trading_days_per_year: int = 252


# ─── Risk limits ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.25   # ≤25% of equity in any single ETF
    max_drawdown_killswitch: float = 0.20  # flatten to cash if DD exceeds this
    min_cash_buffer: float = 0.0        # fraction always held in cash


# ─── Backtest / cost assumptions ─────────────────────────────────────────
@dataclass(frozen=True)
class CostModel:
    # Realistic retail costs. Alpaca commission is $0, but spread + slippage are real.
    commission_per_share: float = 0.0
    slippage_bps: float = 2.0           # 2 bps each side on liquid ETFs (conservative)
    spread_bps: float = 1.0             # half-spread cost assumption
    short_borrow_bps_annual: float = 100.0  # ~1%/yr borrow on short ETF notional


@dataclass(frozen=True)
class Settings:
    params: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskLimits = field(default_factory=RiskLimits)
    costs: CostModel = field(default_factory=CostModel)
    starting_capital: float = 100_000.0


SETTINGS = Settings()
