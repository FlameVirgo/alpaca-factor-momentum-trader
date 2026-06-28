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
TSMOM_UNIVERSE: List[str] = ["SPY", "QQQ", "IWM", "TLT", "GLD", "EFA"]

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


@dataclass(frozen=True)
class Settings:
    params: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskLimits = field(default_factory=RiskLimits)
    costs: CostModel = field(default_factory=CostModel)
    starting_capital: float = 100_000.0


SETTINGS = Settings()
