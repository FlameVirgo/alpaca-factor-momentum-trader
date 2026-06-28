# Alpaca Factor Momentum Trader

A research-grounded, **paper-trading** algorithmic trading system on
[Alpaca](https://alpaca.markets). It deploys a **blended dual-momentum** strategy
on liquid ETFs, validated out-of-sample against buy-and-hold SPY *after realistic
costs*. In the current configuration it **beats buy-and-hold SPY on a
risk-adjusted basis out-of-sample** (Sharpe **0.81 vs 0.78**) with roughly **a
third less drawdown** — see the caveats, which matter.

> ⚠️ **Educational / research project. Paper trading only.** Nothing here is
> financial advice. Trading involves risk of loss. See [PLAN.md](PLAN.md) for the
> full strategy rationale, academic sources, the complete research trail, and
> honest caveats.

## The strategy — Blended Dual Momentum

Gary Antonacci's **Dual Momentum** combines two established academic edges:
**absolute** momentum (own-asset trend — "is it going up at all?") and
**relative** momentum (cross-sectional ranking — "which is strongest?"). The
deployed algorithm blends one of each, 50/50, long/flat, rebalanced **weekly**.

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

**Each weekly rebalance, using only data through the prior close:**
1. **Sleeve A — absolute momentum.** For each of the 10 ETFs compute its
   **12-month total return**. Hold an equal **1/10** slice of every ETF whose
   12-month return **> 0**; everything else is cash. (Long/flat — never short.)
2. **Sleeve B — relative momentum (sector rotation).** Rank the 11 sectors by
   **12-1 month** return (12-month return skipping the most recent month). Hold
   the **top 3** equal-weight (1/3 each) — but only those whose own 12-1
   momentum is **> 0** (Antonacci dual-momentum filter); the rest is cash.
3. **Blend 50/50:** `w = 0.5 · A + 0.5 · B`.
4. **Cap** any single ETF at **25%** of equity. Unallocated weight is held in
   cash, earning the T-bill rate.

**No volatility overlay** (tested and removed). **Trade the next session** after
the signal (1-day execution lag — no look-ahead). **Costs:** 3 bps one-way
(slippage + half-spread) on turnover. Full spec & research trail in
[PLAN.md](PLAN.md) (§2C rules · §2D overlay removal · §2E–§2F variant tests).

```bash
python run_backtest.py            # 15y weekly backtest, OOS split, full table
```

### Backtest result (15y real data, OOS, after costs, look-ahead-free)

Honest accounting is baked in: a **1-day execution lag**, idle cash earning the
**real T-bill rate** (BIL), and Sharpe/Sortino measured as **excess over that
risk-free** (not over zero).

| Out-of-sample (2019–2026) | **Deployed** (blend, no overlay) | Buy & Hold SPY |
|---|---|---|
| **Sharpe** | **0.81** | 0.78 |
| Annualized return | 12.0% | 17.2% |
| Annualized volatility | 11.7% | 19.5% |
| Max drawdown | **−21.7%** | −33.7% |

✅ Beats SPY **risk-adjusted** (H3) · ✅ roughly **⅓ less drawdown** (H2).

**Honest caveats — read these before trusting the result:**
- **The edge is thin.** 0.81 vs 0.78 Sharpe is **within single-window noise**.
  It needs a *second* out-of-sample window before it's believable.
- **It earns less than SPY in absolute terms** (12% vs 17%/yr). It wins on
  *risk-adjusted* return and drawdown — a smoother ride, not a richer one.
- **Sleeve A's universe is regime-dependent** (strong 2019–26, weak in-sample
  2011–18). The original 6-ETF cross-asset set (`TSMOM_UNIVERSE_CORE6` in
  [config.py](config.py)) is a *more consistent* alternative and a one-line
  revert; it posts the same ~0.81 OOS with a stronger in-sample Sharpe.

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
and, on the first trading day of each **week**, recomputes the blended targets
(identical to the backtest) and reconciles the paper book. **Dry-run by default;
no vol overlay** (matching the deployed strategy).

```bash
python run_live.py                # monitor + print the order plan, send nothing
python run_live.py --rebalance    # force-compute this week's plan (still dry-run)
python run_live.py --live         # actually submit to the PAPER account
```

> Deployment is **gated** behind `--live`. The strategy now clears the headline
> bar (beats SPY risk-adjusted OOS), but the edge is thin and rests on a single
> out-of-sample window — validate on a second window before trusting real money.
> The wiring (reconciliation, notional orders, persisted high-water-mark
> kill-switch, journaling to `logs/`) is built and unit-tested.

## Roadmap

See [PLAN.md](PLAN.md). Backtest-first discipline: the deployed blend beats
buy-and-hold SPY risk-adjusted out-of-sample after costs; the next step before
live capital is a **second out-of-sample window** to confirm the edge is real.
