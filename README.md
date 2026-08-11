# Aussie Agent Fleet

A multi-market trading agent fleet for Australian retail conditions: crypto
(24/7, multi-venue), ASX + US stocks, commodity futures, and FX — coordinated
by a portfolio-level risk manager with hard kill-switches, trading paper by
default and live only through deliberate interlocks.

## Honest expectations — read this first

This project was inspired by a viral "turned $68 into $750K with a trading
bot" post. That story does not survive arithmetic: cross-exchange crypto gaps
are usually **smaller than the round-trip taker fees**, and genuine HFT
arbitrage needs capital parked on every venue plus colocation-grade latency.
This fleet's arb monitor shows you the truth live: most cycles, the best
net-of-fees spread is *negative*. When a real dislocation appears it acts —
and the rest of the time the trend/mean-reversion agents do the patient work.

Most retail algo strategies lose money after costs. The correct order is:
**backtest on real data → paper trade for weeks → tiny live sizes → scale
only what proved itself.** Nothing here is financial advice.

## What it does

The Kraken path is intentionally split into proposing and authorizing layers:

```text
Kraken WebSocket v2 (ticker / L2 book / OHLC / trades)
  -> regime + momentum + reversal + volatility votes
  -> probability and cost-adjusted expected-value ensemble
  -> deterministic risk contract (freshness, spread, size, exposure,
     daily loss, drawdown, 90-day max hold, kill switch)
  -> CCXT spot executor
```

The L2 collector verifies Kraken's CRC32 checksum before publishing a book.
An agent cannot bypass the risk contract, and the Kraken adapter rejects
margin, opening shorts, synthetic/stale inputs, and live cross-venue arb.

```
                    ┌─────────────────────────────┐
                    │        Coordinator          │  15s cycle, state.json,
                    │  (stops, halt, kill file)   │  dashboard.html
                    └──────────┬──────────────────┘
      ┌──────────┬─────────────┼─────────────┬────────────┐
 crypto_arb  crypto_momentum  stocks   commodities        fx
 net-of-fee  EMA12/26 1h      SMA20/50 Donchian 20/10     z-score
 x-venue     + RSI filter     momentum close-channel      reversion
 scanner                      + RSI(2) dip                ±2σ / exit 0.5σ
      └──────────┴─────┬───────┴─────────────┴────────────┘
                ┌──────▼───────┐        ┌────────────────────┐
                │ Risk manager │──────▶ │ Executors           │
                │ sizing, caps │        │ paper (default)     │
                │ daily stop,  │        │ ccxt live (crypto)  │
                │ drawdown kill│        │ OANDA live (fx)     │
                └──────────────┘        │ IBKR live (stocks/  │
                                        │  futures, via TWS)  │
                                        └────────────────────┘
```

Every quote is tagged with its source (`kraken`, `yahoo`, `sim:okx`…) so
synthetic data can never masquerade as live. With no internet, the whole fleet
runs against a labelled synthetic market — that's the offline demo/test mode.
The default paper profile enables all six top-level agents. Its crypto ensemble
also runs all four voters (regime, momentum, reversal, and volatility) before
the hard risk contract sees an intention.

## Quickstart

```bash
pip install -r requirements.txt

python run.py --reset            # paper trade on real data, runs forever
python run.py --cycles 60        # bounded run
python run.py --sim --cycles 60  # offline synthetic demo
python backtest/backtest.py      # backtest the rule-sets on ~2y of real data
python tests/test_engine.py      # 21 deterministic engine checks
python tests/test_market_data.py # Kraken v2 schema + official checksum fixture
python tests/test_healthcheck.py # stale-state and stream integrity probes
```

Open `dashboard.html` in a browser — it re-renders every few cycles and
auto-refreshes: equity curve, open positions, the arb monitor, agent notes,
recent trades, event log, and the active risk limits.

Stop everything gracefully: `Ctrl-C`. Emergency flatten from another
terminal: `touch state/KILL`.

## Risk systems (all on by default)

Per-trade sizing from stop distance (0.75% equity at risk), a 5% single
position cap, a 40% per-market-class cap, gross leverage capped at 1.0x, max
12 open positions, a 2%/day loss gate that stops new entries, protective
stops enforced by the coordinator every cycle, a 6% drawdown kill-switch that
flattens the book and halts, and the manual `state/KILL` file. Arb legs
execute atomically — both legs approved or neither trades.

## Configuration

Everything lives in `config.yaml`: markets and symbols, per-agent intervals
and thresholds, fees/slippage for paper fills, and every risk limit. The
`risk.max_gross_leverage: 1.0` default is deliberate — raise it only after
reading the ASIC leverage-cap notes in `docs/GOING_LIVE.md`.

## Going live (real money)

Live order flow exists for crypto (CCXT/Kraken by default), FX (OANDA), and
stocks/futures (Interactive Brokers via a locally running TWS/Gateway) — but
it refuses to arm unless **all** interlocks pass: `mode: live` in config, the
`--live` flag, venue API keys in environment variables, live (non-synthetic)
data feeds, and `LIVE_TRADING_ACK=I_UNDERSTAND_THE_RISKS` in the environment.
Per-order notional is hard-capped (`execution.live.max_order_notional_aud`,
default A$200) while you build trust.

**Read `docs/GOING_LIVE.md` before arming anything** — Australian brokers and
exchanges with real APIs, ASIC's retail leverage caps, API-key security
(withdrawal-disabled keys only), the live-arb inventory problem, tax record
keeping, and a 24/7 VPS deployment guide.

## Project layout

```
run.py                  entrypoint
config.yaml             all knobs
fleet/coordinator.py    cycle loop, atomic arb handling, halt logic
fleet/risk.py           sizing + every limit
fleet/portfolio.py      AUD ledger, positions, trades.jsonl
fleet/datafeeds.py      ccxt / yahoo / stooq / sim providers + router
fleet/agents/           six fleet agents + four crypto ensemble voters
fleet/execution/        paper + ccxt/OANDA/IBKR live executors
fleet/dashboard.py      self-contained HTML dashboard
backtest/backtest.py    vectorised rule-set backtests
tests/test_engine.py    deterministic engine verification
docs/GOING_LIVE.md      the real-money checklist
```

## Production deployment

The production split keeps execution and secrets on the Sydney VPS while
Vercel serves a read-only dashboard:

```text
GitHub main -> Actions tests -> SSH deploy -> OVH Docker Compose
                                         |-> Kraken fleet
                                         |-> PostgreSQL snapshots
                                         |-> authenticated monitor API
Vercel dashboard -> Kraken public data + Yahoo research data
                 -> token-authenticated HTTPS -> monitor API
```

On the VPS, clone the repository to `/opt/trading-bot`, copy `.env.example` to
`.env`, replace every placeholder, and run `bash deploy/preflight.sh`. The
container runs in paper mode unless the VPS-local `.env` contains the exact
live acknowledgement. Kraken keys and PostgreSQL are never sent to Vercel.
The deployment installs `trading-bot.service`, which re-establishes the Docker
Compose project after a host reboot. Compose restart policies, bounded logs,
and freshness-aware health checks cover the fleet, Kraken stream, collector,
monitor, Caddy, and PostgreSQL services.

Configure these GitHub Actions secrets in the `production` environment:

- `OVH_HOST` and `OVH_USER`
- `OVH_SSH_KEY` (a deploy-only private key)
- `OVH_KNOWN_HOSTS` (the pinned `ssh-keyscan` output verified out of band)

Configure `MONITOR_ORIGIN` and `MONITOR_TOKEN` in Vercel. The origin is the
HTTPS hostname in `MONITOR_DOMAIN`; the token must match the VPS `.env`.
Pushes to `main` run tests, build the image, and deploy that exact commit.

The public portal uses Kraken REST/WebSocket data for crypto and a separate,
failure-isolated Yahoo Finance chart feed for gold, silver, crude oil, AUD/USD,
S&P 500, ASX 200, and BHP. Yahoo values are labelled delayed/research-only and
are never treated as executable Kraken prices.

## Disclaimers

Not financial advice; for education and personal use. Trading involves risk
of loss; leveraged products can lose more than deposits. Paper results model
fees and slippage but not every real-world cost (spreads widen, fills queue,
venues go down). You are responsible for compliance with your local laws and
your venues' terms of service.
