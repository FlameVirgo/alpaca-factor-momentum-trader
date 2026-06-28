# Alpaca Factor Momentum Trader

A research-grounded, **paper-trading** algorithmic trading system on
[Alpaca](https://alpaca.markets). It deploys a diversified ensemble of
low-turnover factor strategies with a conservative volatility-targeting overlay,
validated out-of-sample against buy-and-hold SPY *after realistic costs*.

## The strategy — Regime-Hedged Dual Momentum (RHDM)

The components are *established* academic edges; the contribution here is the **synthesis**.
RHDM extends Antonacci's **Dual Momentum** (absolute + relative momentum) with three of my
own design choices:

1. **Cross-asset convex crash hedge** — the absolute-momentum sleeve trades equities *and*
   bonds/gold (TLT/GLD/EFA), so it can go long safe-havens in an equity crash (the behavior
   that gave trend-following positive 2008 returns). Convexity exactly when the sector
   sleeve hurts.
2. **Portfolio-level conservative vol targeting** — one capped overlay (leverage ≤ 1.0, can
   only *de-risk*), avoiding the documented out-of-sample failure of aggressive
   vol-management.
3. **Cost-survivorship as a design filter** — strategies that die after realistic costs
   (overnight, short-term reversal) are *excluded by design*; everything rebalances monthly
   on liquid ETFs.

The thesis: blending a **concave** sleeve (sector rotation) with a **convex** sleeve
(cross-asset trend) under a de-risking overlay targets a higher Sharpe and shallower
drawdowns than either alone. This is a **falsifiable hypothesis** the backtester must
confirm out-of-sample, after costs, vs. buy-and-hold SPY — see [PLAN.md](PLAN.md) §2A.

| Sleeve | Edge | Source |
|---|---|---|
| Time-Series (absolute) Momentum on cross-asset ETFs | Sharpe ~1.28, crash hedge | Moskowitz/Ooi/Pedersen (2012) |
| Cross-Sectional (relative) Momentum — sector rotation | Top-3 of 11 SPDR sectors | Jegadeesh/Titman lineage |
| Volatility-Targeting overlay (conservative) | De-risk in vol spikes | Moreira & Muir (2017) |
| Dual-momentum framing | Absolute + relative combined | Antonacci, *Dual Momentum* (2014) |

### The exact rules (monthly rebalance, no look-ahead, after costs)

1. **Sleeve A (absolute momentum):** of `{SPY, QQQ, IWM, TLT, GLD, EFA}`, hold an
   equal 1/6 slice of each asset whose **12-month return > 0**, else cash.
2. **Sleeve B (relative momentum):** rank the 11 SPDR sectors by **12-1 month**
   return, hold the **top 3** equal-weight — but only the ones whose own
   momentum is positive (dual-momentum filter), else cash.
3. **Blend** 50/50, apply a **capped vol overlay** (scale = min(1.0, 10% /
   trailing-realized-vol) — de-risk only), then **cap any name at 25%**.
4. **Costs:** 3 bps one-way (slippage + half-spread) charged on turnover.

Full implementation-precise spec in [PLAN.md §2C](PLAN.md). Run it yourself:

```bash
python run_backtest.py            # 15y backtest, OOS split, full summary table
```

### Backtest result (15y real data, OOS, after costs, look-ahead-free)

The backtester runs with honesty controls baked in — a **1-day execution lag**
(no acting on the close you used to decide), **idle cash earning the real T-bill
rate** (BIL), and **Sharpe measured as excess over that risk-free**. It honestly
flags a problem: the full RHDM with the vol overlay scores **Sharpe 0.57 OOS vs
0.78 for buy-and-hold SPY** — it does *not* beat SPY risk-adjusted (H1/H3 fail),
and is in fact the weakest line tested. It *does* cut max drawdown hard
(**−22% vs −34%**, H2 passes). The vol overlay is the drag
(blended-without-overlay = Sharpe 0.75). Per the success criteria this means
**do not deploy as-is** — simplify the overlay and re-test first. See
[PLAN.md §2D](PLAN.md) for the full table and the path forward. This is the
backtest-first discipline working exactly as intended: evidence before execution.

## Security

- API keys are loaded from a **gitignored `.env`** — never committed.
- Only `.env.example` (placeholders) is in the repo.
- The system is hardwired to the **paper endpoint** by default.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your Alpaca PAPER keys into .env

python run_backtest.py        # research: 15y backtest + OOS summary (no keys needed)
python -m pytest tests/ -q    # offline unit tests (reconciliation + kill-switch)
```

### Live (paper) deployment — Phase 2 plumbing

`run_live.py` is the daily scheduler entrypoint: it checks the drawdown
kill-switch and, on the first trading day of each month, recomputes RHDM targets
(identical to the backtest) and reconciles the paper book. **Dry-run by default.**

```bash
python run_live.py                # monitor + print the order plan, send nothing
python run_live.py --rebalance    # force-compute today's plan (still dry-run)
python run_live.py --live         # actually submit to the PAPER account
```

> Deployment is intentionally **gated**: per the backtest (§2D) RHDM isn't yet
> validated, so `--live` is off by default. The wiring (reconciliation, notional
> orders, persisted high-water-mark kill-switch, journaling to `logs/`) is built
> and unit-tested; simplify the vol overlay and re-validate before going `--live`.

## Roadmap

See [PLAN.md](PLAN.md). Backtest-first: no live wiring until a strategy beats
buy-and-hold SPY risk-adjusted, out-of-sample, after costs.
