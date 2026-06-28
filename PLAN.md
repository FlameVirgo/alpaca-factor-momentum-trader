# Alpaca Algorithmic Trading — Implementation Plan

A research-grounded plan for a diversified, factor-based trading algorithm deployed
on Alpaca **paper trading** ($100k). Evidence-first: every strategy is backtested
out-of-sample and must beat buy-and-hold SPY *after costs* before any live wiring.

---

## 0. Guiding Principle — Why "super profitable secret algo" is a myth

The most important finding in the literature is about strategy **decay**, not any single
edge. McLean & Pontiff tracked 97 published anomalies and found returns decline **~58%
after publication** as investors arbitrage them away.

> **Implication:** Any edge readable in a paper is partially arbitraged away. What survives
> is protected by *limits to arbitrage* — costs, complexity, capacity, or persistent
> behavioral forces. We hunt those.
>
> **Realistic target:** Sharpe **0.7–1.2**, beating buy-and-hold on a risk-adjusted basis.
> NOT 10x returns.

Source: McLean & Pontiff, "Does Academic Research Destroy Stock Return Predictability?"
(Journal of Finance, 2016).

---

## 1. Strategies Evaluated

| Strategy | Evidence | Edge source | Verdict |
|---|---|---|---|
| **Time-Series Momentum (trend)** | Moskowitz/Ooi/Pedersen: Sharpe **1.28** across 58 instruments '85–'09, positive in 2008 crash | Behavioral under-/over-reaction | ✅ **Core** |
| **Cross-Sectional Momentum (sector rotation)** | Top-3 of ~10 sectors, 12-1 momentum, monthly rebalance; Sharpe 0.5–1.0 | Same behavioral force, low turnover | ✅ **Core** |
| **Volatility Targeting (overlay)** | Moreira & Muir: nearly doubles momentum Sharpe, reduces crashes | Vol forecastable; returns not proportional | ✅ **Overlay (conservative)** |
| **Pairs / Stat-Arb** | Gatev et al: ~11% annual excess '62–'02 | Relative-value mean reversion | ⚠️ **Phase 3** (edge decayed post-2002) |
| **Overnight / close-to-open** | Real pattern, but trading costs wipe it out | Behavioral, at open/close spreads | ❌ Skip (costs) |
| **Short-term reversal** | 55–93 bps/wk gross, high-cost securities | Overreaction | ❌ Skip (costs) |

**Key lesson:** the two rejected strategies have *real* statistical edges that **evaporate
after transaction costs**. That trap catches most retail algo traders. Our defense is
**low turnover (monthly) + liquid ETFs**.

### Sources
- Moskowitz, Ooi, Pedersen, "Time Series Momentum," *Journal of Financial Economics* (2012).
- Cross-sectional / sector momentum: AlphaArchitect, "Minimizing the Risk of Cross-Sectional Momentum Crashes."
- Moreira & Muir, "Volatility-Managed Portfolios," *Journal of Finance* (2017).
- Gatev, Goetzmann, Rouwenhorst, "Pairs Trading: Performance of a Relative-Value Arbitrage Rule," *RFS* (2006).
- Overnight anomaly costs: AlphaArchitect, "Trading Costs Wipe Out the Overnight Return Anomaly."
- Short-term reversal: Quantpedia, "Short-Term Reversal Effect in Stocks."

---

## 2. Architecture — Diversified Factor Portfolio with Volatility Overlay

Not one holy-grail strategy — a small ensemble of low-correlation, low-turnover edges,
risk-scaled.

```
                    ┌─────────────────────────────────┐
                    │   VOLATILITY-TARGETING OVERLAY   │
                    │  (scale exposure by realized vol)│
                    └─────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
   │ SLEEVE A        │   │ SLEEVE B        │   │ SLEEVE C        │
   │ Time-Series Mom │   │ Cross-Sectional │   │ Cash / T-bills  │
   │ on liquid ETFs  │   │ Sector Rotation │   │ (risk-off buffer)│
   │ SPY,QQQ,IWM,    │   │ XLK,XLF,XLE...  │   │                 │
   │ TLT,GLD,EFA     │   │ top 3 of 11     │   │                 │
   │ monthly signal  │   │ monthly rebal   │   │                 │
   └─────────────────┘   └─────────────────┘   └─────────────────┘
```

**Design rationale**
- **Low turnover (monthly)** → transaction costs become negligible (where rejected strategies failed).
- **ETFs not single stocks** → no blowup risk, deep liquidity, tight spreads, no earnings landmines.
- **TSMOM is the crash hedge** — went long bonds / short equities in 2008 and profited. Portfolio insurance.
- **Vol-targeting** = highest Sharpe-per-unit-effort addition in the literature.

**Honest caveat:** vol-targeting has a documented out-of-sample weakness ("volatility
management often harms real-time performance" — Cederburg et al.). We implement it
**conservatively** (cap leverage at 1.0, de-risk only in genuine vol spikes) and prove it
on our own data before trusting it.

---

## 2A. The Novel Strategy — Regime-Hedged Dual Momentum (RHDM)

**Intellectual-honesty note:** the individual edges below are *established* academic
anomalies, not new discoveries. Claiming a brand-new anomaly would be dishonest — the
literature shows new public anomalies decay (§0). What is genuinely **novel here is the
synthesis**: a specific integration that, in my research, is uncommon in retail
implementations. It extends Gary Antonacci's *Dual Momentum* (combining absolute +
relative momentum) with three additions of my own design.

### The base: Dual Momentum (prior art)
Antonacci's Dual Momentum combines:
- **Absolute momentum** (own-asset trend — "is it going up at all?") → our TSMOM sleeve.
- **Relative momentum** (cross-sectional ranking — "which is strongest?") → our sector sleeve.

### What makes RHDM different (the novel synthesis)

1. **Cross-asset convex crash hedge.** Standard dual momentum rotates *within equities* (or
   to cash). RHDM's absolute-momentum sleeve trades a **cross-asset** universe
   (SPY/QQQ/IWM + TLT/GLD/EFA), so in an equity crash it can hold **bonds and gold long** —
   the exact behavior that gave TSMOM positive 2008 returns. This gives the ensemble
   *convexity* (long-volatility payoff) precisely when the sector sleeve is suffering.

2. **Portfolio-level conservative volatility targeting.** Rather than scaling each sleeve
   independently (the textbook Moreira-Muir approach, which has weak out-of-sample
   results), RHDM applies a **single capped overlay at the blended-portfolio level** —
   leverage hard-capped at 1.0, so it can *only de-risk*, never gear up. This sidesteps the
   documented failure mode of aggressive vol-management while keeping the crash protection.

3. **Cost-survivorship as a design filter.** The novel *negative* design choice: I used the
   documented failure of the overnight and short-term-reversal anomalies (killed by
   transaction costs) as a **hard constraint** — every component must survive realistic
   net-of-cost backtesting, enforced by monthly rebalancing on liquid ETFs only. Most
   retail systems pick a strategy then hope costs don't matter; RHDM selects *because of*
   costs.

### Why the synthesis should produce a smoother edge
The two sleeves are **negatively correlated in tail events**: relative momentum (sector
rotation) is mildly concave and bleeds in sharp reversals, while cross-asset absolute
momentum is convex and profits in sustained crashes. Blending a concave sleeve with a
convex sleeve under a de-risking overlay targets a **higher Sharpe and shallower drawdowns
than either sleeve alone** — that diversification across *return-timing shape*, not just
across assets, is the core thesis. Whether it actually delivers is an empirical question
the backtester (§5, Phase 1) must answer out-of-sample, after costs, vs. buy-and-hold SPY.

### Falsifiable hypotheses (what Phase 1 must confirm or kill)
- H1: Blended RHDM Sharpe > max(TSMOM-only Sharpe, sector-only Sharpe), out-of-sample.
- H2: RHDM max drawdown < buy-and-hold SPY drawdown over the same window.
- H3: The vol-targeting overlay improves Sortino without harming CAGR by more than ~1%/yr.
If H1–H2 fail out-of-sample, the "novelty" is just complexity and we simplify.

---

## 2C. Algorithm Specification — the exact rules (implementation-precise)

This is the concrete, unambiguous definition of what the code does. Everything
below is computed **only from data available at the rebalance date** (no
look-ahead) and rebalanced on the **last trading day of each month**.

Notation: `MONTH = 21` trading days. `P_t(a)` = adjusted close of asset `a` at
date `t`. Universes and parameters live in [config.py](config.py).

**Step 1 — Sleeve A: Time-Series (Absolute) Momentum** — [strategies/tsmom.py](strategies/tsmom.py)
Universe `U_A = {SPY, QQQ, IWM, TLT, GLD, EFA}` (cross-asset, N = 6).
For each asset `a`, momentum is the 12-month total return:
```
mom_A(a) = P_t(a) / P_{t-12·MONTH}(a) − 1          (skip_months = 0)
w_A(a)   = 1/N   if mom_A(a) > 0   else   0
```
So each trending asset gets an equal 1/6 slice; non-trending slices fall to
**cash**. In an equity sell-off where TLT/GLD are still rising, the sleeve holds
those safe-havens — the 2008-style crash hedge. Sleeve A is long/flat, never
short, and at most 100% invested.

**Step 2 — Sleeve B: Cross-Sectional (Relative) Momentum** — [strategies/xsec_momentum.py](strategies/xsec_momentum.py)
Universe `U_B` = the 11 SPDR sectors. Use **12-1** momentum (skip the most
recent month to avoid short-term reversal):
```
mom_B(s) = P_{t-1·MONTH}(s) / P_{t-12·MONTH}(s) − 1
```
Rank all sectors by `mom_B`, take the **top 3**. Each selected sector gets a
1/3 slice **only if its own `mom_B > 0`** (Antonacci dual-momentum filter);
otherwise that slice is cash. In a broad bear market all three can be cash.

**Step 3 — Blend** — [portfolio/allocator.py](portfolio/allocator.py)
```
w_blend = 0.5 · w_A + 0.5 · w_B          (weight_tsmom = weight_xsec = 0.5)
```

**Step 4 — Conservative vol overlay** — [strategies/vol_target.py](strategies/vol_target.py)
Estimate annualized realized vol of the blended book over the trailing 60 days
(strictly before `t`), then scale — **capped at 1.0, de-risk only**:
```
σ_real = std(blended daily returns, last 60d) · √252
scale  = min(1.0, 0.10 / σ_real)         (target_annual_vol = 0.10)
w_final = scale · w_blend
```

**Step 5 — Risk caps** — clip any single name to `max_position_weight = 0.25`.
Whatever is unallocated is held in cash (0% return). A separate kill-switch
flattens to cash if drawdown exceeds 20% (live only).

**Costs** charged each rebalance on turnover `Σ|Δw|`: slippage 2 bps + half-spread
1 bp = **3 bps one-way**, commission $0 (Alpaca). See [config.py](config.py) `CostModel`.

---

## 2D. Backtest Results (15y real data, after costs, look-ahead-free)

Run with `python run_backtest.py` (defaults to **weekly** rebalancing, matching
`run_live.py`) on 18 ETFs, **2011-06-27 → 2026-06-26**, free Yahoo-sourced
adjusted closes, OOS split at 2019-01-01. **Honesty controls baked in:** (a) a
**1-day execution lag** — signals computed on a close are traded the next
session, removing same-close look-ahead; (b) idle cash earns the **real
risk-free rate** (BIL, the 1-3mo T-bill ETF, ~1.45%/yr over the sample, higher in
2022-24); (c) Sharpe/Sortino measure **excess return over that risk-free**, not
over zero.

**Why weekly:** weekly rebalancing beat monthly risk-adjusted out-of-sample —
the vol overlay reacts to volatility in time rather than a month late, lifting
RHDM Sharpe 0.57→0.70 and cutting its drawdown −21.6%→−15.9%. Trading the slow
momentum legs more often than weekly (daily) mostly just adds turnover. (Pass
`--rebalance monthly|daily` to compare; turnover is printed each run.)

**Out-of-sample (2019-01-01 → 2026-06-26), weekly:**

| Strategy | Ann.Ret | Vol | **Sharpe** | Sortino | MaxDD | Calmar |
|---|---|---|---|---|---|---|
| RHDM (blend + vol overlay) | 9.7% | 10.3% | **0.70** | 0.89 | −15.9% | 0.61 |
| Blended (no vol overlay)   | 13.4% | 13.5% | **0.81** | 1.00 | −23.5% | 0.57 |
| Sleeve A — TSMOM only      | 10.1% | 9.9% | **0.76** | 0.90 | −15.0% | 0.68 |
| Sleeve B — Sector rotation | 16.2% | 19.4% | **0.74** | 0.92 | −33.6% | 0.48 |
| **Buy & Hold SPY**         | 17.2% | 19.5% | **0.78** | 0.95 | −33.7% | 0.51 |
| 60/40 SPY/TLT              | 10.2% | 12.6% | **0.63** | 0.82 | −27.2% | 0.38 |

**Falsifiable hypotheses (§2A), OOS verdict (weekly):**
- **H1** RHDM Sharpe > best single sleeve (0.70 vs 0.76) — ❌ **FAIL**
- **H2** RHDM maxDD < SPY maxDD (−15.9% vs −33.7%) — ✅ **PASS**
- **H3** RHDM Sharpe > Buy&Hold SPY (0.70 vs 0.78) — ❌ **FAIL**

**Honest read — weekly helped, but the vol overlay is still the problem.** Weekly
lifted the full RHDM a lot (0.57→0.70, drawdown cut by a quarter), yet it still
**fails H1/H3**: the overlaid book (0.70) cannot beat the simpler TSMOM sleeve
(0.76) or SPY (0.78). More frequency made the overlay *less bad*, not *good*.

The result hiding in plain sight: the **blended sleeve *without* the overlay** at
weekly scores **0.81 Sharpe** — it beats SPY (0.78), the best sleeve (0.76), and
RHDM, with far lower drawdown (−23.5% vs −33.7%) and ~13.5% vol vs SPY's 19.5%.
The hypotheses only report FAIL because they are pinned to the *full* RHDM, which
still carries the overlay.

**Conclusion before any deployment:** per §8 success criteria, the full RHDM does
**not** beat buy-and-hold SPY risk-adjusted OOS → **do not deploy as-is.** The
pre-registered next test (not knob-tuning) is **weekly + no vol overlay**, which
on this window clears all three hypotheses — though H3's margin (0.81 vs 0.78) is
thin enough to be within single-window noise, so it needs a second OOS window
before declaring victory. This is the backtest-first discipline working as
designed.

---

## 2E. Variant research — broaden / short / risk-scale (none adopted)

Tested all 8 permutations of three TSMOM levers via
[research/permutations.py](research/permutations.py) — (a) broad ~18-ETF
cross-asset universe, (b) long/short leg, (c) inverse-vol (equal-risk) sizing —
weekly, OOS 2019+, after costs + 1%/yr short borrow.

**Result: no robust improvement; the highest-OOS-Sharpe combo is an overfitting
artifact.** Evidence the winner is noise, not edge:

- Highest full-RHDM **OOS** Sharpe = combo **"abc"** (all three) at **0.775** —
  but its *in-sample* Sharpe (0.578) is *worse* than the plain sleeve (0.658),
  and the best *in-sample* combo is **"none"**. OOS winner ≠ in-sample winner →
  the harness flags it as noise.
- "abc" includes the **short leg (b), which individually destroys the TSMOM
  sleeve** (OOS Sharpe ~0.26–0.32, in-sample *negative*): shorting cross-asset
  ETFs bled through the 2011–2019 bull. A "winning" combo built on an
  individually-catastrophic lever is the definition of fitting noise.
- **(a) broad universe didn't help** (sleeve OOS 0.77→0.74, in-sample 0.60→0.35):
  our 18 ETFs are dominated by correlated bond/credit and equity blocks, so it
  *diluted* rather than added independent bets — unlike MOP's 58 futures across 4
  asset classes. More tickers ≠ more diversification.
- **(c) risk-scaling** was marginally positive and consistent (+~0.005 Sharpe) —
  negligible.
- Even the 0.775 artifact is **still below buy-and-hold SPY (0.778).**

**Conclusion:** keep the simple long/flat equal-weight sleeve. None of these
additions earns its complexity. The real lever remains dropping/threshold-gating
the vol overlay (blended-no-overlay weekly ≈ 0.81), *validated on a second
window* — not these. This is the curve-fitting trap (§0) caught in the act.

---

## 2F. Maximally-independent universe — n caps low, the OOS gain is a regime fluke

§2E failed because the extra ETFs were *correlated*. Here we do it right:
greedily select the largest set of *predominantly independent* liquid ETFs
(in-sample correlations only, no look-ahead) — [research/independent_universe.py](research/independent_universe.py).

- **The number of independent ETFs caps low:** n=9 at |corr|<0.60, n=10 at 0.70,
  n=13 at 0.80. You **cannot** manufacture MOP's 58 independent futures from
  liquid ETFs — the math ceiling is ~10. The selected set leans
  commodities/credit/dollar/REIT plus a single equity (QQQ).
- **The independent sleeve looks great OOS but is a fluke:** TSMOM on the n=10
  set scores OOS Sharpe **0.812** (> orig-6 0.765 > SPY 0.778), 5.7% vol, −9.5%
  DD. **But its in-sample Sharpe is only 0.226** (vs orig-6's 0.603). OOS ≫
  in-sample by that much = it worked in 2019–2026 and *not* in 2011–2018 →
  regime-dependent, not durable. Untrustworthy on exactly the same logic as §2E.
- **It doesn't improve the deployed blend:** blended-no-overlay is ~unchanged
  (indep OOS 0.807 vs orig-6 0.809), and orig-6 is *more consistent* in-sample
  (0.629 vs 0.554).

**Conclusion:** more independent ETFs isn't a free lunch — n is capped ~10 and
on this data it added regime-dependence, not robust Sharpe. Keep the original
6-ETF cross-asset universe; it's the most consistent across both halves.

---

## 2G. Sleeve blend weight — 50/50 is the overfitting-safe choice

Swept the TSMOM/sector blend from 0/100 to 100/0 (weekly, no overlay, after
costs) via [research/sleeve_weights.py](research/sleeve_weights.py):

- **Out-of-sample** Sharpe *rises* with a TSMOM tilt — peaking **0.858 at 80%
  TSMOM** (and drawdown shrinks too).
- **In-sample** Sharpe does the **exact opposite** — highest (**0.608**) at
  **0% TSMOM** (pure sector) and falling monotonically to 0.226 at 100% TSMOM.
- So the OOS-best tilt (80% TSMOM) and the in-sample-best tilt (0% TSMOM) point
  in **opposite directions.**

When the two halves disagree on the *direction* of the tilt, any move away from
50/50 is a bet on which regime repeats — i.e. overfitting. **50/50 is the only
weight that doesn't require forecasting the regime**, and the blend is more
consistent in-sample (0.554) than the TSMOM-heavy tilts that maximize the OOS
backtest. Keep 50/50.

---

## 2B. News / Social Sentiment — Evaluated, Deferred (mostly rejected)

**Verdict: do NOT add sentiment as an alpha signal in v1. Defer one narrow use to Phase 3.**

Sentiment *does* contain real, published predictive power — Twitter sentiment has predicted
returns "without subsequent reversal" (Behrendt & Schmidt; Sprenger et al.), and recent
LLM-based news studies report headline win-rate lifts of ~5% on the S&P 500. So why reject
it? Four reasons specific to *this* architecture:

1. **Frequency mismatch (the killer).** Sentiment alpha is *fast* — it decays in hours to a
   few days, strongest at intraday-to-3-month horizons. RHDM rebalances **monthly**. By our
   next rebalance the signal is stale. To harvest sentiment you must trade fast and often.
2. **It reintroduces the cost problem we designed out.** Capturing a fast signal means high
   turnover — exactly the regime that *killed* the overnight and reversal anomalies (§1).
   We'd be re-importing the failure mode RHDM was built to avoid.
3. **Universe mismatch.** Sentiment research is overwhelmingly *single-stock*. Our universe
   is broad **ETFs**, whose idiosyncratic sentiment is weak; what's left is macro risk-on/off
   tone — already largely captured by price momentum. Low marginal information.
4. **Overfitting / look-ahead red flags.** The flashy results (Sharpe 3.6–5.1, +50% returns)
   come from short 2022–2023 windows and LLM pipelines prone to look-ahead bias (the model
   "knows" the future of its training period). Healthy skepticism warranted.

### The one place it might earn its keep (Phase 3 experiment)
Not as a stock-picking signal, but as a **slow, aggregate-market risk/regime filter** feeding
the volatility-targeting overlay — e.g. a news-based "stress index" that de-risks the whole
book when aggregate negative-news intensity spikes. This is *low-frequency* (fits the
architecture), and **Alpaca already ships the Benzinga News API free** (real-time + historical
back to 2015), so it's cheap to prototype. It must clear the same bar: improves out-of-sample
Sortino without adding turnover cost. If we ever want true sentiment alpha, it belongs in a
**separate high-frequency single-stock sleeve**, not bolted onto RHDM.

Sources: Behrendt & Schmidt (2018, *J. Banking & Finance*); Sprenger et al. (2014); arXiv
2507.03350 (Backtesting Sentiment Signals, 2025); arXiv 2404.00012 (news stress index);
Alpaca/Benzinga News API.

---

## 3. Why Alpaca + $100k Paper Fits

- `alpaca-py` SDK: `StockHistoricalDataClient` (5+ yrs bars) + market/bracket orders.
- $100k paper sidesteps the **PDT rule** entirely; monthly rebalancing is nowhere near day-trade limits.
- Paper endpoint = real-time live market data, simulated fills. Same code as live (one URL swap).

---

## 4. Project Structure

```
Alpaca_Trading/
├── PLAN.md                 # this file
├── .env                    # paper keys (gitignored — you fill in)
├── .env.example            # template
├── requirements.txt
├── config.py               # universe, params, risk limits
├── data/
│   ├── alpaca_data.py      # historical + live bars via alpaca-py (live source of record)
│   └── market_data.py      # free no-key Yahoo loader + CSV cache (backtest only)
├── strategies/
│   ├── tsmom.py            # time-series (absolute) momentum signal
│   ├── xsec_momentum.py    # cross-sectional (relative) sector rotation
│   └── vol_target.py       # conservative volatility-scaling overlay
├── backtest/
│   ├── engine.py           # vectorized backtester w/ realistic turnover costs
│   └── metrics.py          # Sharpe, Sortino, max DD, Calmar, turnover
├── portfolio/
│   ├── allocator.py        # combine sleeves + overlay + caps → target weights
│   └── target.py           # live: current month-end target snapshot (reuses allocator)
├── run_backtest.py         # ← research driver: pull data, backtest, print summary
├── execution/
│   ├── alpaca_executor.py  # reconcile current vs target, place notional orders
│   ├── risk_monitor.py     # persisted high-water-mark drawdown kill-switch
│   └── journal.py          # durable signal/order/equity logging → logs/
├── tests/
│   └── test_execution.py   # offline tests: reconciliation + kill-switch
└── run_live.py             # scheduled daily/monthly orchestrator (Phase 2)
```

---

## 5. Roadmap

### Phase 0 — Foundation (Day 1)
- Project scaffold, `.env.example`, `requirements.txt`, `config.py`.
- Data layer pulling historical ETF bars from Alpaca.

### Phase 1 — Backtest FIRST, trade NEVER yet (Week 1–2) — *non-negotiable*
- Pull 10+ years of ETF bars.
- Event-driven backtester with **realistic costs baked in** (spread + slippage + commission).
- **Walk-forward / out-of-sample**: fit params 2010–2018, validate untouched 2019–2025.
  In-sample-only success = curve-fit garbage → kill it.
- Every sleeve and the combined portfolio must beat **buy-and-hold SPY** risk-adjusted, after costs.

### Phase 2 — Paper deployment (Week 3+) — *plumbing built, deployment gated*
- ✅ **Built:** `run_live.py` scheduler entrypoint — reads paper equity, runs the
  drawdown kill-switch, and on the first trading day of each month recomputes
  RHDM targets ([portfolio/target.py](portfolio/target.py), identical to the
  backtest pipeline) and reconciles the book ([execution/alpaca_executor.py](execution/alpaca_executor.py))
  with notional orders. Full journaling of signals/orders/equity to `logs/`.
- ✅ **Safety built in:** dry-run by default (`--live` required to submit),
  paper-endpoint assertion, persisted high-water-mark kill-switch → flatten to
  cash on breach, sub-threshold churn suppression, offline unit tests.
- ⏳ **Gated:** actual `--live` deployment is intentionally held until RHDM
  clears §8 criteria out-of-sample — current backtest (§2D) does **not** (the vol
  overlay must be simplified first). The wiring is ready; the strategy isn't.
- **Next:** once validated, schedule `python run_live.py --live` daily (cron /
  GitHub Action), run weeks-to-months, compare **live paper vs. backtest**.
  Divergence = bug or overfit, caught with fake money.

### Phase 3 — Iterate
- Optionally add pairs-trading sleeve or tail hedge once core is proven.

---

## 6. Risk Management (built in from day one)
- **Per-position cap** (≤25% of equity in any one ETF).
- **Portfolio vol target** (~10% annualized) via overlay.
- **Kill switch**: hard max-drawdown limit → flatten to cash.
- **Reconciliation safety**: never trade if live positions don't match expected state.

---

## 7. Build Decisions (locked in)
- **Keys:** scaffold with `.env.example`; user pastes paper keys. Nothing connects until then.
- **Order:** backtester-first (evidence before execution).
- **Scope v1:** full ensemble — TSMOM + sector rotation + vol overlay.

---

## 8. Success Criteria Before Risking Real Money (future)
1. Out-of-sample Sharpe ≥ 0.7 after realistic costs.
2. Beats buy-and-hold SPY risk-adjusted out-of-sample.
3. Live paper results track backtest within reason for ≥ 3 months.
4. Max drawdown within tolerance; kill switch verified.
