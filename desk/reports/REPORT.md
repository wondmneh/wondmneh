# Desk report, 2026-11-17 18:48 UTC

Data: 20 OKX USDT perpetuals, 1H candles, 2022-11-17 to 2026-11-17. Sources and download times are in `data/manifest.json`.

Costs in every test: 0.05% taker fee per fill, slippage 0.02% (BTC, ETH) or 0.05% (others) per fill (ESTIMATE), and funding (OKX for the last 3 months, Binance as a proxy before that: ESTIMATE).

## Verdict

**No strategy passed every check, so nothing is cleared for real money.** 3 passed everything except beating BTC hold on return per unit of drawdown during the validation window, which was a bull market (BTC +152.6%). They are on the podium as PROVISIONAL, for paper trading only.

## Leaderboard (walk-forward, after all costs)

| Strategy | Regime | Validation | Holdout | 3-year return | Max DD | Sharpe | Trades | Fees x2 | Nearby | Score | Failed checks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tsmom | trending | +26.9% | +28.9% | +63.6% | -27.1% | 0.89 | 776 | +54.8% | 100% | 13/25 | beats_hold_risk_adj |
| volume_surge_breakout | trending | +109.9% | -12.5% | +83.6% | -31.9% | 0.75 | 1916 | +9.6% | 100% | 13/25 | beats_hold_risk_adj, unseen_holdout |
| ema_cross | trending | +45.4% | +10.5% | +60.6% | -37.8% | 0.66 | 593 | +59.2% | 100% | 13/25 | beats_hold_risk_adj |
| liq_cascade_reversal | wild | +13.5% | -3.0% | +10.1% | -7.2% | 0.51 | 305 | +0.8% | 67% | 19/25 | nearby_settings, beats_hold_risk_adj, unseen_holdout |
| bear_rally_short | trending | -9.1% | +25.6% | +14.1% | -16.6% | 0.44 | 390 | +7.2% | 17% | 15/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj |
| donchian_trend | trending | +8.5% | +5.6% | +14.6% | -15.1% | 0.41 | 440 | +10.9% | 83% | 14/25 | beats_hold_risk_adj |
| xs_momentum | trending | +1.8% | +8.1% | +10.1% | -15.6% | 0.40 | 707 | +5.5% | 50% | 13/25 | fees_doubled, nearby_settings, beats_hold_risk_adj |
| funding_carry_trend | trending | +2.4% | +1.4% | +3.8% | -6.3% | 0.39 | 154 | +2.9% | 67% | 14/25 | nearby_settings, beats_hold_risk_adj |
| capitulation_daily | wild | +1.9% | +1.2% | +3.1% | -4.1% | 0.30 | 109 | +2.3% | 56% | 18/25 | nearby_settings, beats_hold_risk_adj |
| squeeze_breakout | ranging | +24.9% | -13.3% | +8.3% | -41.2% | 0.24 | 2114 | -28.9% | 100% | 12/25 | fees_doubled, beats_hold_risk_adj, unseen_holdout |
| donchian_btc_filter | trending | -3.7% | +8.4% | +4.4% | -16.5% | 0.18 | 329 | +1.8% | 83% | 14/25 | unseen_validation, fees_doubled, beats_hold_risk_adj |
| rel_strength_breakout | trending | +5.1% | -4.2% | +0.6% | -16.3% | 0.07 | 306 | -1.7% | 100% | 11/25 | beats_hold_risk_adj, unseen_holdout |
| trend_pullback | trending | -19.0% | +11.6% | -9.6% | -38.2% | -0.05 | 1701 | -31.3% | 50% | 11/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj |
| nr_breakout | ranging | -13.5% | -2.2% | -15.4% | -24.8% | -0.18 | 2245 | -35.0% | 33% | 11/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj, unseen_holdout |
| funding_extreme_fade | wild | -16.1% | +2.1% | -14.4% | -23.4% | -0.45 | 212 | -17.1% | 67% | 11/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj |
| btc_lead_alt_lag | wild | -40.7% | -0.8% | -41.2% | -45.0% | -0.96 | 1254 | -65.6% | 0% | 9/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj, unseen_holdout |
| bb_meanrev_range | ranging | -60.8% | +15.5% | -54.7% | -66.6% | -0.99 | 2597 | -73.3% | 0% | 11/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj |
| rsi2_dip | trending | -28.1% | -10.5% | -35.7% | -46.1% | -1.09 | 1669 | -51.1% | 0% | 12/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj, unseen_holdout |
| funding_flip | trending | -11.4% | -9.0% | -19.4% | -20.3% | -1.19 | 219 | -20.6% | 0% | 9/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj, unseen_holdout |
| panic_snapback | wild | -45.1% | -21.4% | -56.9% | -67.6% | -1.36 | 1434 | -70.4% | 0% | 9/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj, unseen_holdout |
| xs_reversal | ranging | -17.9% | -10.7% | -26.7% | -27.4% | -1.39 | 2216 | -35.2% | 0% | 11/25 | unseen_validation, fees_doubled, nearby_settings, beats_hold_risk_adj, unseen_holdout |

Holding instead, over the same 3 years: BTC +72.9% (max drawdown -53.8%); all 20 coins equally weighted -17.7% (max drawdown -79.4%).

Checks: `unseen_validation` = Profitable on walk-forward data it was not fitted on; `unseen_holdout` = Profitable on the final holdout year; `trades_50` = At least 50 out-of-sample trades; `fees_doubled` = Still profitable with fees and slippage doubled; `nearby_settings` = At least 70% of nearby settings profitable; `no_lookahead` = No future data leak (truncation test); `beats_hold_risk_adj` = Beat holding on return per unit of drawdown in the validation window.

## Strategy cards

### Provisional champion: `donchian_trend` (trending markets)

**Idea.** Buy new N-day highs and short new N-day lows.

**Why the edge exists, and who loses.** Big moves start as breakouts and holders react late; people fading the breakout pay.

**Rules.** Daily close above the prior n-day high: long (below the n-day low: short). Exit on a close through the n/2-day opposite channel. Stop and trail k x daily ATR(20).

**Settings going into paper trading.** `{"n": 60, "k": 2.0}`, chosen on the last 365 days only.

**Position size.** Risk 0.5% of equity to the stop; at most 1x equity per position, 3x in total and 8 positions (when more than 8 coins signal, the 8 most liquid take the slots). In the backtest the typical position was 4% of equity and was held 5.3 days.

**Results after fees, slippage and funding (out-of-sample, walk-forward).**

| Period | Strategy return | Max drawdown | Sharpe | Trades | Hold BTC | Hold all 20 coins |
|---|---|---|---|---|---|---|
| Validation (2023-11-21 to 2025-11-18) | +8.5% | -13.9% | 0.36 | 325 | +152.6% | +68.4% |
| Holdout (2025-11-18 to 2026-11-17) | +5.6% | -9.7% | 0.54 | 115 | -31.6% | -51.1% |
| All 3 years | +14.6% | -15.1% | 0.41 | 440 | +72.9% (drawdown -53.8%) | -17.7% (drawdown -79.4%) |

**Walk-forward.** 7 of 12 quarterly folds profitable: +1.7%, +2.6%, +4.9%, -1.0%, +8.4%, -2.9%, -4.4%, -0.4%, +1.4%, -6.7%, +5.3%, +6.0%.

**Worst month.** -3.8% (2024-10). **Longest losing streak.** 15 trades. **Win rate.** 42%. **Costs paid.** $184 fees and $266 funding on a $10,000 account.

**By BTC regime (all 3 years).** Bull +5.7%, bear -15.2%, chop +27.9%.

**Monte Carlo (2,000 reshuffles of the out-of-sample trades).** 5th-percentile return -0.7%, median +19.2%, 95th-percentile drawdown -13.0%, chance of a loss 6%.

**Score (1-5).** Profit 2, drawdown 2, trade count 5, losing streak 2, bear and chop 3. Total 14/25.

**With the Guardian switched on** (flatten at -3% on the day or 3 losses in a row, 24h pause; current settings, 3 years): +24.7% with drawdown -13.1% and 45 halts, against +24.7% and -14.0% without it.

**Final check.**

- Wins on data it has never seen? Validation Yes, holdout Yes.
- After fees and funding? Yes, all numbers above include them.
- Across 50+ trades? Yes (440).
- With fees doubled? Yes: +10.9% over the 3 years.
- Across nearby settings? Yes: 83% of the grid profitable in validation, median Sharpe 0.30.
- Anything leak from the future? No, by the truncation test.
- Beats simply holding? NO in validation (return/drawdown 0.61 against BTC 4.72). Over all 3 years: 0.97 against BTC 1.36 and the 20-coin basket -0.22.

**Market that breaks it.** Choppy ranges with repeated false breakouts. **Earliest warning sign.** Breakouts reversing inside 3 days more than usual.

**WHY THIS COULD FAIL.** It made less money than holding BTC through the bull market, so its case rests on smaller drawdowns, not higher returns. It was the survivor of 21 ideas, so some of its result is selection luck. The coin list contains only contracts still listed today, slippage is an estimate, and funding before the last 3 months is a Binance proxy. Choppy ranges with repeated false breakouts.

### Provisional challenger 1: `ema_cross` (trending markets)

**Idea.** Be long while the fast 4H average is above the slow one, short when below.

**Why the edge exists, and who loses.** Trends persist; traders anchored to old prices pay.

**Rules.** 4H EMA(fast) crosses above EMA(slow): long; crosses below: short (always reverses). Stop 4 x 4H ATR(14).

**Settings going into paper trading.** `{"fast": 50, "slow": 200}`, chosen on the last 365 days only.

**Position size.** Risk 0.5% of equity to the stop; at most 1x equity per position, 3x in total and 8 positions (when more than 8 coins signal, the 8 most liquid take the slots). In the backtest the typical position was 5% of equity and was held 13.0 days.

**Results after fees, slippage and funding (out-of-sample, walk-forward).**

| Period | Strategy return | Max drawdown | Sharpe | Trades | Hold BTC | Hold all 20 coins |
|---|---|---|---|---|---|---|
| Validation (2023-11-21 to 2025-11-18) | +45.4% | -33.1% | 0.71 | 417 | +152.6% | +68.4% |
| Holdout (2025-11-18 to 2026-11-17) | +10.5% | -17.4% | 0.56 | 176 | -31.6% | -51.1% |
| All 3 years | +60.6% | -37.8% | 0.66 | 593 | +72.9% (drawdown -53.8%) | -17.7% (drawdown -79.4%) |

**Walk-forward.** 6 of 12 quarterly folds profitable: +20.1%, +27.9%, -2.5%, +11.3%, +10.2%, -1.1%, -7.9%, -13.2%, +7.4%, -13.2%, -0.4%, +18.9%.

**Worst month.** -9.4% (2024-01). **Longest losing streak.** 23 trades. **Win rate.** 24%. **Costs paid.** $736 fees and $1,721 funding on a $10,000 account.

**By BTC regime (all 3 years).** Bull +81.6%, bear -24.1%, chop +16.6%.

**Monte Carlo (2,000 reshuffles of the out-of-sample trades).** 5th-percentile return -11.1%, median +51.8%, 95th-percentile drawdown -29.6%, chance of a loss 10%.

**Score (1-5).** Profit 3, drawdown 1, trade count 5, losing streak 1, bear and chop 3. Total 13/25.

**With the Guardian switched on** (flatten at -3% on the day or 3 losses in a row, 24h pause; current settings, 3 years): +4.4% with drawdown -22.7% and 77 halts, against +105.1% and -31.4% without it.

**Final check.**

- Wins on data it has never seen? Validation Yes, holdout Yes.
- After fees and funding? Yes, all numbers above include them.
- Across 50+ trades? Yes (593).
- With fees doubled? Yes: +59.2% over the 3 years.
- Across nearby settings? Yes: 100% of the grid profitable in validation, median Sharpe 0.72.
- Anything leak from the future? No, by the truncation test.
- Beats simply holding? NO in validation (return/drawdown 1.37 against BTC 4.72). Over all 3 years: 1.60 against BTC 1.36 and the 20-coin basket -0.22.

**Market that breaks it.** Sideways markets with repeated crossings. **Earliest warning sign.** Crossings per month rising.

**WHY THIS COULD FAIL.** It made less money than holding BTC through the bull market, so its case rests on smaller drawdowns, not higher returns. It was the survivor of 21 ideas, so some of its result is selection luck. The coin list contains only contracts still listed today, slippage is an estimate, and funding before the last 3 months is a Binance proxy. Sideways markets with repeated crossings.

### Provisional challenger 2: `tsmom` (trending markets)

**Idea.** Go with the sign of each coin's own trailing return.

**Why the edge exists, and who loses.** Time-series momentum from slow reaction and herding; contrarians pay.

**Rules.** Daily: lb-day return > 0: long, < 0: short. Reverses on a sign change. Stop k x daily ATR(20).

**Settings going into paper trading.** `{"lb": 14, "k": 3.0}`, chosen on the last 365 days only.

**Position size.** Risk 0.5% of equity to the stop; at most 1x equity per position, 3x in total and 8 positions (when more than 8 coins signal, the 8 most liquid take the slots). In the backtest the typical position was 3% of equity and was held 3.2 days.

**Results after fees, slippage and funding (out-of-sample, walk-forward).**

| Period | Strategy return | Max drawdown | Sharpe | Trades | Hold BTC | Hold all 20 coins |
|---|---|---|---|---|---|---|
| Validation (2023-11-21 to 2025-11-18) | +26.9% | -27.1% | 0.63 | 618 | +152.6% | +68.4% |
| Holdout (2025-11-18 to 2026-11-17) | +28.9% | -8.9% | 1.67 | 158 | -31.6% | -51.1% |
| All 3 years | +63.6% | -27.1% | 0.89 | 776 | +72.9% (drawdown -53.8%) | -17.7% (drawdown -79.4%) |

**Walk-forward.** 7 of 12 quarterly folds profitable: +1.3%, +18.5%, -8.3%, +20.6%, +8.9%, -0.7%, -3.2%, -8.7%, +13.3%, +2.1%, -1.4%, +13.0%.

**Worst month.** -6.8% (2025-10). **Longest losing streak.** 17 trades. **Win rate.** 36%. **Costs paid.** $510 fees and $628 funding on a $10,000 account.

**By BTC regime (all 3 years).** Bull +47.6%, bear -14.6%, chop +29.8%.

**Monte Carlo (2,000 reshuffles of the out-of-sample trades).** 5th-percentile return +14.4%, median +64.4%, 95th-percentile drawdown -13.8%, chance of a loss 0%.

**Score (1-5).** Profit 3, drawdown 1, trade count 5, losing streak 1, bear and chop 3. Total 13/25.

**With the Guardian switched on** (flatten at -3% on the day or 3 losses in a row, 24h pause; current settings, 3 years): +7.3% with drawdown -15.4% and 139 halts, against +55.1% and -15.4% without it.

**Final check.**

- Wins on data it has never seen? Validation Yes, holdout Yes.
- After fees and funding? Yes, all numbers above include them.
- Across 50+ trades? Yes (776).
- With fees doubled? Yes: +54.8% over the 3 years.
- Across nearby settings? Yes: 100% of the grid profitable in validation, median Sharpe 0.81.
- Anything leak from the future? No, by the truncation test.
- Beats simply holding? NO in validation (return/drawdown 0.99 against BTC 4.72). Over all 3 years: 2.34 against BTC 1.36 and the 20-coin basket -0.22.

**Market that breaks it.** Range-bound markets where the sign flips constantly. **Earliest warning sign.** Sign flips per month rising.

**WHY THIS COULD FAIL.** It made less money than holding BTC through the bull market, so its case rests on smaller drawdowns, not higher returns. It was the survivor of 21 ideas, so some of its result is selection luck. The coin list contains only contracts still listed today, slippage is an estimate, and funding before the last 3 months is a Binance proxy. Range-bound markets where the sign flips constantly.

## Deleted

- `donchian_btc_filter`: failed 3 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; Beat holding on return per unit of drawdown in the validation window).
- `squeeze_breakout`: failed 3 checks (Still profitable with fees and slippage doubled; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `trend_pullback`: failed 4 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window).
- `panic_snapback`: failed 5 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `funding_extreme_fade`: failed 4 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window).
- `funding_carry_trend`: failed 2 checks (At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window).
- `volume_surge_breakout`: failed 2 checks (Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `liq_cascade_reversal`: failed 3 checks (At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `btc_lead_alt_lag`: failed 5 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `xs_momentum`: failed 3 checks (Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window).
- `xs_reversal`: failed 5 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `bb_meanrev_range`: failed 4 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window).
- `rsi2_dip`: failed 5 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `nr_breakout`: failed 5 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `funding_flip`: failed 5 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `capitulation_daily`: failed 2 checks (At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window).
- `rel_strength_breakout`: failed 2 checks (Beat holding on return per unit of drawdown in the validation window; Profitable on the final holdout year).
- `bear_rally_short`: failed 4 checks (Profitable on walk-forward data it was not fitted on; Still profitable with fees and slippage doubled; At least 70% of nearby settings profitable; Beat holding on return per unit of drawdown in the validation window).
