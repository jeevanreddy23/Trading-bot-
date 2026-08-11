# Going live — the Australian checklist

This is the part that protects your money. Work through it in order. Nothing
in this document is financial, legal, or tax advice — it's an engineering
checklist plus pointers to the rules that apply to Australian retail traders.

## 0. The burn-in rule

Do not send a live order until the fleet has paper-traded **on real data**
for at least four weeks and you have looked at every trade it took and can
explain why. Then start with `execution.live.max_order_notional_aud` at
A$50–200. Scale only what proved itself. If a strategy can't beat its costs
on paper, it will do worse live.

## 1. Accounts and APIs that work from Australia

| Market | Venue | API | Notes |
|---|---|---|---|
| Crypto spot | Kraken | REST/WS via ccxt | AUD pairs, solid API docs; default live venue here |
| Crypto spot | BTC Markets | REST via ccxt (`btcmarkets`) | Sydney-based, AUD books; higher taker fees |
| Crypto spot | Coinbase / OKX / Bybit | via ccxt | availability of products for AU accounts varies — check current AU terms |
| ASX + US stocks, futures | Interactive Brokers Australia | TWS API via `ib_insync` | the practical algo broker for ASX; requires TWS/IB Gateway running locally (paper port 7497, live 7496) |
| FX | OANDA | v20 REST | free practice environment — ideal FX burn-in; live account for real |
| CFDs (indices, commodities) | Pepperstone / IC Markets (ASIC-regulated) | MT5/FIX | not integrated in this fleet by default |

Binance's Australian derivatives licence was cancelled in 2023 — treat
Binance as a data source rather than an execution venue for AU accounts, and
verify current AUD deposit/withdrawal support yourself.

Futures through IBKR require a margin account and product permissions; ASX
stocks settle T+2 and the fleet's stocks agent is long-only by default.

## 2. ASIC rules that shape what you can do

ASIC's product intervention order on CFDs (in force since March 2021,
extended in 2022 to **23 May 2027**) caps retail leverage: **30:1** major FX
pairs, **20:1** minor FX/gold/major indices, **10:1** other commodities,
**5:1** shares, **2:1** crypto-assets, with negative balance protection and
standardised margin close-outs. That is why `max_gross_leverage: 1.0` is the
default here — raise it only within those bounds and only with a reason.
Automated trading for your own account is legal; trading *other people's*
money or selling signals generally requires an AFS licence — don't.

## 3. API key hygiene (non-negotiable)

Create keys with **trade permission only — never withdrawal permission**.
Enable the venue's IP allowlist and pin it to your server. Keep keys in
environment variables or a `.env` file that is never committed (see
`.env.example`). Use a dedicated trading account holding only what the bot
is allowed to lose. Rotate keys if anything ever looks off.

## 4. Arming sequence

1. `config.yaml`: `mode: live` (and pick `execution.live.crypto_venue`).
2. Export keys: `KRAKEN_API_KEY/SECRET`, `OANDA_API_TOKEN/ACCOUNT_ID`.
3. For stocks/futures: install `ib_insync`, run IB Gateway, log in.
4. `export LIVE_TRADING_ACK=I_UNDERSTAND_THE_RISKS`
5. `python run.py --live`

The coordinator arms each market's live executor independently and logs what
armed; markets without a live executor **skip** new entries rather than
silently paper-trading. Watch the first hours yourself. `touch state/KILL`
flattens and halts at any time.

## 5. The live-arb reality

Paper mode fills both arb legs CFD-style. Real cross-exchange arb requires
**inventory pre-positioned on both venues** (coins on the expensive venue to
sell, cash on the cheap one to buy) because transfers take minutes-to-hours
while windows close in seconds — and spot venues can't short, so this
fleet's live crypto executor refuses arb sell legs. Treat the arb agent as a
**monitor/alert** in live trading unless you deliberately build the
two-venue inventory setup. The monitor's day job is showing you that gross
gaps are usually smaller than fees — that lesson is free; live tuition on it
is expensive.

## 6. Tax and records (Australia)

Crypto disposals are generally CGT events for investors; frequent systematic
trading may instead be treated as trading stock / ordinary income — the
distinction matters and depends on facts, so ask a registered tax agent.
Every fill is appended to `state/trades.jsonl` — keep it, along with venue
statements. The ATO receives data from Australian exchanges; keep records of
every trade, fee, and AUD value at the time.

## 7. Running 24/7

Cheapest reliable setup: a small VPS (Sydney region keeps latency to ASX/AU
venues low).

```bash
docker build -t fleet .
docker run -d --restart unless-stopped --env-file .env \
  -v $(pwd)/state:/app/state --name fleet fleet
```

or a systemd unit:

```ini
[Unit]
Description=Aussie Agent Fleet
After=network-online.target

[Service]
WorkingDirectory=/opt/aussie-agent-fleet
EnvironmentFile=/opt/aussie-agent-fleet/.env
ExecStart=/usr/bin/python3 run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Check `dashboard.html` (serve the folder with any static server or just open
the file), tail `state/fleet.log`, and set an uptime monitor on the state
file's modification time. IBKR execution can't run on a headless VPS without
IB Gateway + IBC; many people run stocks live from a home machine and
crypto/FX from the VPS.

## 8. When to stop

Stop and reassess if: the daily loss gate trips twice in a week; live fills
are consistently worse than paper assumed (slippage model too kind); a
strategy's live Sharpe over a month is negative while paper was positive; or
you find yourself raising limits to "win it back". The kill file costs
nothing to use.
