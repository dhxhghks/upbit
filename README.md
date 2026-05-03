# Upbit Simple Auto Trader

Minimal Python auto-trading sample for Upbit Korea. It starts with a simple moving-average strategy and uses hard safety defaults.

This is engineering sample code, not financial advice. Real-money trading can lose money. Start with `paper`, then `test`, then use a very small amount in `live`.

## Files

- `get_btc_price.py`: public KRW-BTC ticker sample.
- `simple_auto_trader.py`: one-shot or loop trading bot.
- `coin_status_web.py`: local browser dashboard for market, strategy, and balance monitoring.
- `.env`: environment variables to configure the bot.

## Strategy

The first strategy is intentionally simple:

- Buy when short SMA is above long SMA.
- Sell when short SMA is below long SMA.
- Hold otherwise.

The bot stores the last signal in `STATE_FILE` so a loop does not send the same order every cycle.

## Setup

Put your local settings in `.env`. The scripts load this file automatically and
exported shell variables override matching `.env` values.

```bash
UPBIT_ACCESS_KEY=
UPBIT_SECRET_KEY=
TRADING_MODE=paper
MARKET=KRW-BTC
WATCHLIST=KRW-BTC,KRW-ETH,KRW-XRP
MOMENTUM_SURGE_PCT=1.2
MOMENTUM_VOLUME_MULTIPLIER=2.0
```

## Run Paper Mode

Paper mode fetches candles and prints the intended order. It does not need API keys.

```bash
python3 simple_auto_trader.py --once
```

Loop mode:

```bash
python3 simple_auto_trader.py --loop --interval 300
```

## Run Coin Status Web App

The web app shows public market status without API keys. If `UPBIT_ACCESS_KEY` and
`UPBIT_SECRET_KEY` are present in `.env`, it also shows account balances.

```bash
python3 coin_status_web.py --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in your browser. The watchlist page is available
at `http://127.0.0.1:8000/watchlist` and uses the comma-separated `WATCHLIST`
setting from `.env`.

The trading control page is available at `http://127.0.0.1:8000/trading`.
It lets you select a watchlist market, the SMA strategy, paper/test/live mode,
and run one cycle or start a repeated loop. Live mode still requires
`ALLOW_LIVE_TRADING=true` in `.env` and exact market confirmation in the page.
The aggressive watchlist momentum strategy scans every `WATCHLIST` market and
looks for simultaneous price surge and volume spike conditions.

## Run Order Test Mode

This calls Upbit's `/v1/orders/test` endpoint and does not create a real order. Your API key still needs order permission.

```bash
TRADING_MODE=test python3 simple_auto_trader.py --once
```

## Run Live Mode

Live mode can place real orders. The script requires all of these:

- `TRADING_MODE=live`
- `ALLOW_LIVE_TRADING=true`
- `CONFIRM_LIVE_MARKET` equal to `MARKET`
- API key with the required Upbit permissions

```bash
TRADING_MODE=live ALLOW_LIVE_TRADING=true CONFIRM_LIVE_MARKET=KRW-BTC python3 simple_auto_trader.py --once
```

For the first live run, keep `ORDER_KRW` at the exchange minimum or another very small amount.
