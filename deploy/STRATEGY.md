# Strategy: Swing Growth (for ~$6k–$10k paper / savings)

## Plain-English idea

Think of the stock market like weather:

- **Uptrend (sunny):** it’s safer to go outside (buy stocks).
- **Downtrend (storm):** stay inside (hold cash).

This bot only buys when the big market (SPY, a fund of 500 large US companies) looks healthy. Then it buys a **small basket** of stocks the model likes, and attaches a plan to **take profit** or **cut losses**—like setting a sell order if the trip goes well or badly.

It is **not** gambling on tiny same-day moves. The old ±1.5% brackets were like leaving the party after 10 minutes. The new rules aim for **multi-day swings**.

## What we are aiming for

| Goal | Reality check |
|------|----------------|
| **~10%+ / year** | Possible in good years with discipline; **not guaranteed**. Long-term US stocks historically average ~8–10%/year *before* your strategy adds/subtracts. |
| **~20% / year** | Aggressive. Some years yes, many years no. Treat as a stretch, not a promise. |
| **Reliable income** | Trading is **not** a paycheck. For true reliability, most of savings should sit in broad index funds; this bot is a **satellite** (practice / growth sleeve). |

**Best use of $10k savings (honest split):**

- **70–80%** boring long-term (e.g. SPY/VOO)—this is how most people compound.
- **20–30%** paper/live “active sleeve” until paper proves itself for months.

## Rules (what the code does)

1. **Market filter:** trade only if SPY is above its 50-day and 200-day averages (uptrend). Otherwise: **no new buys**.
2. **Fewer stocks:** up to **8** names (quality over quantity).
3. **Risk sizing:** each name sized so a stop-loss loses about **~1% of account** (capped by budget).
4. **Exits:** stop about **2.5%** below entry; take profit about **5%** above (**~2:1** reward:risk).
5. **Once per weekday** near the open—no all-day overtrading.
6. **Whole shares only** (Alpaca bracket limit)—expensive mega-caps may still be skipped.

## Why this is better than the old bot

| Old | New |
|-----|-----|
| Buy many names every 30 minutes | Buy fewer names **once** in the morning |
| ±1.5% stops (noise) | Wider swing exits |
| Always trade | Sit out weak markets |
| Equal tiny dollars | Size by risk + mild conviction |

## What “good” looks like after 1–2 months of paper

- Not every day has trades (regime filter working).
- More winners that run to ~5% than instant stop-outs.
- Drawdowns hurt but don’t wipe the account.
- You can explain every trade: “model liked it, market was up, risk was ~1%.”

If stop-outs still dominate, widen stops further or trade even fewer names—don’t add complexity.
