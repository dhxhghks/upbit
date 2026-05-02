# Strategies

This project currently has one simple moving-average strategy. It is intentionally
basic and is meant as a monitored starting point, not financial advice.

## Simple SMA Crossover

The strategy reads recent Upbit minute candles for `MARKET` and compares two
simple moving averages:

- `SHORT_SMA`: short moving-average window, default `5`
- `LONG_SMA`: long moving-average window, default `20`
- `CANDLE_UNIT`: minute candle unit, default `5`
- `CANDLE_COUNT`: number of candles fetched, default `60`

The bot reverses Upbit candle order before calculating averages so the newest
close is last in the price list.

## Signal Rules

- `buy`: short SMA is greater than long SMA
- `sell`: short SMA is less than long SMA
- `hold`: short SMA equals long SMA

In code:

```text
if short_sma > long_sma: buy
if short_sma < long_sma: sell
otherwise: hold
```

## Order Rules

For a `buy` signal:

- Use a KRW market buy order.
- Spend `ORDER_KRW`.
- If account balances are available, skip the buy when it would reduce KRW
  below `MIN_KRW_BALANCE`.

For a `sell` signal:

- Use a market sell order.
- Sell `SELL_RATIO` of the base coin balance.
- Skip the sell if no base coin balance is available.
- In paper mode, sell orders are not calculated because paper mode does not
  fetch private account balances.

For a `hold` signal:

- No order is created.

## Duplicate Signal Guard

The bot stores the last signal per mode and market in `STATE_FILE`.

If the current signal is the same as the previous signal, it skips order
creation. This prevents the loop from repeatedly sending the same order every
cycle while the signal has not changed.

## Trading Modes

- `paper`: no private API call and no real order
- `test`: calls Upbit's test order endpoint
- `live`: calls Upbit's real order endpoint

Live mode is blocked unless all of these are true:

- `TRADING_MODE=live`
- `ALLOW_LIVE_TRADING=true`
- `CONFIRM_LIVE_MARKET` exactly equals `MARKET`

## Main Risk

This strategy reacts only to a short SMA and long SMA relationship. It does not
consider volatility, fees, slippage, order book depth, trend strength, stop loss,
or broader market conditions.
