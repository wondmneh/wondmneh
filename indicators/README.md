# ICT Concepts (TradingView and MT5 indicator)

`ICT_Concepts.pine` (TradingView) and `ICT_Concepts.mq5` (MT5) overlay the concepts from *The ICT Bible – V1* (Ali Khan) on the chart. Both follow the same rules.

**TradingView**: open the Pine Editor, paste the contents of `ICT_Concepts.pine`, then *Add to chart*. Killzones use New York time directly, so there is no broker offset to set.

| Book concept | What is drawn |
|---|---|
| Three-bar swing | Dot on each swing high / low |
| Liquidity (old highs / lows) | Dotted `BSL` / `SSL` lines on swings price has not traded through yet |
| Fair value gap | `BISI` / `SIBI` box with the consequent encroachment (50%) line |
| Order block | `+OB` / `-OB` box with its mean threshold (50%) line |
| Breaker block | `+BRK` / `-BRK` box |
| Mitigation block | `+MB` / `-MB` box |
| Dealing range, premium vs discount | Range high, range low and the 50% line of the latest major swing |
| Killzones | Session boxes: Asia, London, New York, London Close, index AM / PM |
| Power of 3 | 12am New York opening price line |
| SMT divergence | `SMT` line between two swings when a second symbol diverges |

## Rules used

- **FVG**: three candles where the first and third wicks do not overlap.
- **Order block**: when a candle closes through a swing, the last down-close candle(s) before the rally (or up-close before the drop). With `Block must run liquidity past a prior swing` on, the move into the block must also have taken out a prior swing, as the book describes.
- **Breaker**: the swing that was broken, when price first ran liquidity on the other side (higher high then break of the low, or the reverse).
- **Mitigation block**: the same, when price failed to run that liquidity first (lower high then break of the low, or the reverse).
- Zones disappear once a candle closes through them, unless `Keep zones that price has closed through` is on.

## MT5 setup

1. Copy `ICT_Concepts.mq5` to `MQL5/Indicators` and compile it in MetaEditor.
2. Set `Broker server time minus New York time`. The default of 7 fits brokers on GMT+2 / GMT+3 that follow US daylight saving. Check it against your Market Watch clock, since killzones and the midnight open depend on it.
3. For SMT, enter a correlated symbol (for example `GBPUSD` on a `EURUSD` chart) and tick the inverse option for symbols such as a dollar index.

Killzones and the midnight open are drawn on H1 and lower. Everything is calculated from closed candles, so nothing changes after a candle has closed.
