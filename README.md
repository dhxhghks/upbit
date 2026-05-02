# Upbit Simple Auto Trader

Minimal Python auto-trading sample for Upbit Korea. It starts with a simple moving-average strategy and uses hard safety defaults.

This is engineering sample code, not financial advice. Real-money trading can lose money. Start with `paper`, then `test`, then use a very small amount in `live`.

## Files

- `get_btc_price.py`: public KRW-BTC ticker sample.
- `simple_auto_trader.py`: one-shot or loop trading bot.
- `.env.example`: environment variables to configure the bot.

## Strategy

The first strategy is intentionally simple:

- Buy when short SMA is above long SMA.
- Sell when short SMA is below long SMA.
- Hold otherwise.

The bot stores the last signal in `STATE_FILE` so a loop does not send the same order every cycle.

## Setup

```bash
cp .env.example .env
```

Edit `.env` and set your API keys only when you need `test` or `live` mode.

Load the environment:

```bash
set -a
. ./.env
set +a
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
