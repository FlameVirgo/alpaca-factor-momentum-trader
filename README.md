# Alpaca Factor Momentum Trader

A research-grounded, **paper-trading** algorithmic trading system on
[Alpaca](https://alpaca.markets). The deployed strategy is a **core-satellite**:
**50% buy-and-hold SPY** (equity beta) + **50% a blended dual-momentum** book on
liquid ETFs (the diversifying satellite), rebalanced **every 2 trading days**.
Out-of-sample (2019–2026) it **beats buy-and-hold SPY risk-adjusted** (Sharpe
**0.82 vs 0.78**) with lower drawdown — **but read the caveats**: that edge does
*not* hold up reliably over longer windows (it's ~40% to beat SPY over 2012–26).

## The strategy — Core-Satellite (SPY core + dual-momentum satellite)

The **satellite** is Gary Antonacci's **Dual Momentum** — **absolute** momentum
(own-asset trend) blended 50/50 with **relative** momentum (cross-sectional
ranking), long/flat. The **core** is a permanent 50% SPY position that supplies
the equity upside the bare satellite missed. Adding the core raised both the
Sharpe and its in-sample/out-of-sample consistency ([PLAN.md §2K](PLAN.md)).

| Sleeve | What it does | Source |
|---|---|---|
| **A — Absolute (time-series) momentum** | Long/flat on a low-correlation cross-asset ETF set | Moskowitz/Ooi/Pedersen (2012) |
| **B — Relative (cross-sectional) momentum** | Top-3 of 11 SPDR sectors, dual-momentum filtered | Jegadeesh/Titman; Antonacci (2014) |

> **What changed to beat SPY.** Earlier versions carried a conservative
> volatility-targeting overlay and rebalanced monthly. Honest backtesting
> ([PLAN.md §2D](PLAN.md)) showed the **overlay dragged risk-adjusted returns**
> and that **weekly** rebalancing helped. Removing the overlay + rebalancing
> weekly is what lifted the blend from Sharpe 0.57 → **0.81** out-of-sample and
> over the SPY benchmark. Adding a short leg, broadening to correlated ETFs, and
> inverse-vol sizing were all tested and **rejected** as overfitting (§2E–§2F).

### The exact rules (precise specification)

**Universe**
- **Sleeve A** trades the maximally-independent ETF set (chosen by low pairwise
  correlation, n = 10): `QQQ, GLD, USO, DBA, LQD, HYG, SHY, EMB, VNQ, UUP`
  (US equity, commodities, credit/govt/EM bonds, real estate, US dollar).
- **Sleeve B** trades the 11 SPDR sector ETFs (`XLK, XLF, XLE, XLV, XLI, XLY,
  XLP, XLU, XLB, XLRE, XLC`).

**Every 2 trading days, using only data through the prior close:**
1. **Satellite — Sleeve A (absolute momentum).** For each of the 10 ETFs compute
   its **12-month total return**. Hold an equal **1/10** slice of every ETF whose
   12-month return **> 0**; the rest is cash. (Long/flat — never short.)
2. **Satellite — Sleeve B (relative momentum / sector rotation).** Rank the 11
   sectors by **12-1 month** return. Hold the **top 3** equal-weight (1/3 each) —
   but only those whose own 12-1 momentum is **> 0** (dual-momentum filter).
3. **Blend the satellite 50/50:** `sat = 0.5 · A + 0.5 · B`, cap any single ETF
   at **25%**.
4. **Core-satellite:** final book = **0.5 · SPY (core) + 0.5 · sat** (the SPY core
   is exempt from the 25% cap). Unallocated weight earns the T-bill rate.

**No volatility overlay** (tested and removed). **Trade the next session** after
the signal (1-day execution lag — no look-ahead). **Costs:** 3 bps one-way on
turnover. Full spec & research trail in [PLAN.md](PLAN.md) (§2C rules · §2D
overlay removal · §2E–§2F universe · §2J lookback · §2K core-satellite).

```bash
python run_backtest.py            # 15y backtest, OOS split, full comparison table
```

### Backtest result (15y real data, OOS, after costs, look-ahead-free)

Honest accounting is baked in: a **1-day execution lag**, idle cash earning the
**real T-bill rate** (BIL), and Sharpe/Sortino measured as **excess over that
risk-free** (not over zero).

| Out-of-sample (2019–2026) | **Deployed** (core-satellite) | Buy & Hold SPY |
|---|---|---|
| **Sharpe** | **0.82** | 0.78 |
| Annualized return | 14.7% | 17.2% |
| Annualized volatility | 15.1% | 19.5% |
| Max drawdown | **−27.9%** | −33.7% |

✅ Beats SPY **risk-adjusted** (H3) · ✅ lower drawdown (H2) · ✅ beats best sleeve (H1).

**Honest caveats — read these before trusting the result:**
- **"Beats SPY" does NOT hold up over longer windows.** The 2019–2026 win is
  real but window-specific. On 2012–2026 the core-satellite Sharpe is 0.81 vs
  SPY's 0.83, and a 1000× bootstrap puts the probability it beats SPY at only
  **~40%** ([PLAN.md §2K/§2I](PLAN.md)). SPY's modern Sharpe is exceptionally
  hard to beat after costs.
- **It earns less than SPY in absolute terms** (14.7% vs 17.2%/yr). Its durable,
  repeatable edge is **drawdown / crash protection** (−16% vs SPY's −55% in
  2008), not return — think of it as crash-insured equity, not an index-beater.
- **What it reliably is:** a positive-Sharpe book (bootstrap P(Sharpe>0) ≈ 100%)
  that tracks SPY with a diversification cushion.

## Security

- API keys are loaded from a **gitignored `.env`** — never committed.
- Only `.env.example` (placeholders) is in the repo.
- The system is hardwired to the **paper endpoint** by default.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your Alpaca PAPER keys into .env

python run_backtest.py        # research: 15y weekly backtest + OOS summary (no keys needed)
python -m pytest tests/ -q    # offline unit tests (reconciliation + kill-switch)
```

## Live (paper) deployment — Phase 2 plumbing

`run_live.py` is the scheduler entrypoint: it checks the drawdown kill-switch
and, **every 2 trading days**, recomputes the core-satellite targets (identical
to the backtest) and reconciles the paper book. **Dry-run by default.**

```bash
python run_live.py                # monitor + print the order plan, send nothing
python run_live.py --rebalance    # force-compute today's plan (still dry-run)
python run_live.py --live         # actually submit to the PAPER account
```

> Deployment is **gated** behind `--live` (dry-run otherwise). The wiring
> (reconciliation, notional orders, persisted high-water-mark kill-switch,
> journaling to `logs/`) is built and unit-tested. Paper-only: the executor
> refuses any non-paper endpoint unless explicitly overridden.

## Roadmap

See [PLAN.md](PLAN.md). The deployed core-satellite beats buy-and-hold SPY
risk-adjusted on 2019–2026 but not reliably over longer windows — paper-trade it
forward and compare live results to the backtest before any real capital.
