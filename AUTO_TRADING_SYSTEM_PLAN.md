# Upbit Auto Coin Trading System Implementation Plan

This document describes how to build an automated coin trading system using the official Upbit Python SDK and Upbit API. It is a build plan, not a promise of profitability. Implement every phase with paper trading, strict risk limits, monitoring, and manual kill switches before enabling real orders.

## 1. Reference Baseline

Primary references:

- Official Python SDK: https://github.com/upbit-official/upbit-sdk-python
- Upbit API overview: https://docs.upbit.com/kr/reference/api-overview
- Authentication guide: https://docs.upbit.com/kr/reference/auth
- Rate limit guide: https://docs.upbit.com/kr/reference/rate-limits

Key technical points from the references:

- Use `upbit-sdk` for Python 3.9+.
- Use `Upbit` for synchronous code or `AsyncUpbit` for async code.
- Store `UPBIT_ACCESS_KEY` and `UPBIT_SECRET_KEY` in environment variables or `.env`; never commit keys.
- Authenticated Exchange API calls require API keys and JWT-based authentication. The SDK handles this when configured with keys.
- Public market data can use trading pairs, tickers, orderbooks, trades, candles, and public WebSocket streams.
- Private trading requires API key permission groups such as asset lookup, order creation, and order lookup.
- Rate limits must be enforced locally. Upbit returns `Remaining-Req` headers, and 429/418 responses must trigger backoff.

## 2. Target Capabilities

Build the system in this order:

1. Market data collection
2. Strategy signal generation
3. Backtesting and simulation
4. Paper trading
5. Real order execution with small limits
6. Monitoring, alerting, and operations
7. Strategy expansion after stable operation

The first production-ready version should support only a small allowlist of KRW markets, for example `KRW-BTC` and `KRW-ETH`, and only one conservative strategy. Do not start with many markets or high-frequency trading.

## 3. Recommended Architecture

Use a modular Python application:

```text
upbit-trader/
  pyproject.toml
  .env.example
  README.md
  src/
    trader/
      config.py
      logging.py
      upbit_client.py
      rate_limit.py
      market_data/
        collector.py
        candles.py
        websocket.py
      strategy/
        base.py
        moving_average.py
        risk.py
      execution/
        broker.py
        paper_broker.py
        upbit_broker.py
        order_manager.py
      portfolio/
        balances.py
        positions.py
      storage/
        models.py
        repository.py
      app/
        backtest.py
        paper_trade.py
        live_trade.py
  tests/
```

Core design rule: strategy code must not call Upbit directly. Strategy produces an intent, risk management approves or rejects it, and the broker layer executes it.

## 4. Configuration

Create configuration for:

- Upbit environment and API keys
- Market allowlist
- Candle interval and lookback window
- Maximum position size per market
- Maximum total KRW exposure
- Daily loss limit
- Minimum KRW balance reserve
- Order type policy: market, limit, or both
- Dry-run/paper/live mode
- Logging level
- Database path or connection string

Example `.env.example`:

```text
UPBIT_ACCESS_KEY=
UPBIT_SECRET_KEY=
UPBIT_ENVIRONMENT=kr
TRADING_MODE=paper
MARKETS=KRW-BTC,KRW-ETH
MAX_POSITION_KRW=50000
MAX_TOTAL_EXPOSURE_KRW=100000
DAILY_LOSS_LIMIT_KRW=20000
```

Never allow live trading unless `TRADING_MODE=live` is explicit and keys are present.

## 5. API Client Layer

Install the SDK:

```bash
pip install upbit-sdk python-dotenv
```

Create a single client factory:

```python
import os
from upbit import Upbit

def create_upbit_client() -> Upbit:
    return Upbit(
        access_key=os.environ.get("UPBIT_ACCESS_KEY"),
        secret_key=os.environ.get("UPBIT_SECRET_KEY"),
        environment=os.environ.get("UPBIT_ENVIRONMENT", "kr"),
        timeout=20.0,
        max_retries=2,
    )
```

Use SDK methods for:

- Accounts: balance lookup
- Trading pairs: market list
- Tickers: current prices
- Candles: historical OHLCV
- Orderbooks: depth
- Trades: recent executions
- Orders: create, cancel, retrieve, list open, list closed, test create
- WebSocket public/private streams where appropriate

Wrap all SDK calls in an internal `UpbitGateway` so the rest of the system depends on local interfaces, not SDK details.

## 6. Rate Limit Handling

Implement a rate-limit guard before live trading:

1. Parse `Remaining-Req` from raw responses when available.
2. Track per-group remaining second-level capacity.
3. Add local throttling by API group:
   - Quotation market/candle/trade/ticker/orderbook: up to 10 requests per second
   - Exchange default: up to 30 requests per second
   - Order creation and order test: up to 8 requests per second
   - Bulk cancel: up to 1 request per 2 seconds
   - WebSocket connect: up to 5 requests per second
   - WebSocket messages: up to 5 per second and 100 per minute
4. On HTTP 429, stop requests for that group and retry with exponential backoff.
5. On HTTP 418, stop live trading and wait for the returned block period.

For the first version, keep polling intervals conservative and prefer batch market-data requests where the API supports multiple pairs.

## 7. Data Storage

Use SQLite first unless volume requires PostgreSQL.

Persist:

- Candle history
- Ticker snapshots if needed
- Strategy signals
- Simulated orders
- Real orders
- Fills
- Balances
- Position snapshots
- Risk events
- Application health events

Minimum tables:

```text
candles(market, interval, candle_time, open, high, low, close, volume)
signals(id, created_at, market, strategy, side, confidence, reason)
orders(id, created_at, mode, market, side, order_type, price, volume, status, upbit_uuid)
fills(id, order_id, created_at, price, volume, fee)
positions(market, quantity, avg_price, realized_pnl, unrealized_pnl, updated_at)
risk_events(id, created_at, market, event_type, detail)
```

Use unique keys on `(market, interval, candle_time)` to avoid duplicate candle rows.

## 8. Market Data Module

Step-by-step:

1. Load the market allowlist from config.
2. Validate each market exists using Upbit trading pair APIs.
3. Fetch historical candles for the strategy lookback.
4. Store candles in SQLite.
5. Poll candles on a fixed schedule or subscribe through WebSocket if real-time response is required.
6. Normalize all timestamps to UTC internally and display Korea time only in logs/reports when useful.
7. Add data-quality checks:
   - Missing candle detection
   - Duplicate candle rejection
   - Stale price detection
   - Abnormal spread or volume flags

Start with minute or day candles. Avoid tick-level strategies until the execution and monitoring layers are proven.

## 9. Strategy Interface

Define a common strategy contract:

```python
from dataclasses import dataclass
from enum import Enum

class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

@dataclass(frozen=True)
class Signal:
    market: str
    side: Side
    confidence: float
    reason: str

class Strategy:
    name: str

    def generate(self, market: str, candles: list) -> Signal:
        raise NotImplementedError
```

First strategy suggestion:

- Moving-average crossover on candles
- Optional RSI filter
- Fixed position sizing
- Sell on reverse signal, stop loss, or take profit

Keep strategy output simple. Risk management decides actual order size.

## 10. Risk Management

Risk checks must run before every order:

- Market is in allowlist
- Trading mode is correct
- No duplicate open order for the same market and side
- Position size after order is below `MAX_POSITION_KRW`
- Total exposure after order is below `MAX_TOTAL_EXPOSURE_KRW`
- KRW reserve remains above configured minimum
- Daily realized plus unrealized loss is above negative daily limit
- Price slippage estimate is below threshold
- API and market data are fresh
- Kill switch is not active

Implement hard rejection reasons and persist them as `risk_events`.

## 11. Broker And Execution Layer

Create a broker interface:

```python
class Broker:
    def get_balances(self): ...
    def get_open_orders(self, market: str): ...
    def place_order(self, market: str, side: str, order_type: str, price: str | None, volume: str | None): ...
    def cancel_order(self, uuid: str): ...
    def get_order(self, uuid: str): ...
```

Implement two brokers:

- `PaperBroker`: simulates fills using candle close price, ticker price, or orderbook midpoint.
- `UpbitBroker`: calls real Upbit order APIs through the SDK.

Execution rules:

1. Generate target order from approved signal.
2. Use decimal arithmetic, not floats, for KRW and coin quantities.
3. Check order chance before live orders.
4. Use order test API before enabling real order creation.
5. Submit order.
6. Poll or subscribe to private order updates.
7. Reconcile actual fills and fees.
8. Update positions and balances.
9. Cancel stale open orders after a configured timeout.

## 12. Backtesting

Build backtesting before paper trading:

1. Load historical candles from storage.
2. Run strategy over historical windows without lookahead.
3. Simulate fees and slippage.
4. Track cash, positions, realized PnL, drawdown, and trade count.
5. Export results to CSV or JSON.
6. Add tests to catch lookahead bias.

Minimum metrics:

- Total return
- Maximum drawdown
- Win rate
- Profit factor
- Average trade return
- Number of trades
- Fees paid
- Largest loss

Do not use backtest results alone to justify live trading. Use them to reject clearly bad strategies and catch implementation errors.

## 13. Paper Trading

Paper trading should run with the same market data, strategy, risk, and order-manager code as live trading. Only the broker changes.

Paper trading checklist:

- Runs continuously for at least 1-2 weeks
- No unhandled exceptions
- Orders are persisted correctly
- Position state matches simulated fills
- Risk rejections are understandable
- Logs are enough to reconstruct every decision
- Alerts trigger on failures
- Daily report is generated

Only after this should real order testing begin with very small size.

## 14. Live Trading Controls

Before live trading:

- Create API key with only required permissions.
- Register the server IP in the API key allowlist.
- Keep withdrawal permissions disabled unless explicitly needed. A trading bot usually should not need withdrawal permission.
- Use a separate account or isolated balance if possible.
- Set very small `MAX_POSITION_KRW` and `MAX_TOTAL_EXPOSURE_KRW`.
- Enable kill switch by file flag or environment flag.
- Confirm order test API succeeds.
- Confirm balance lookup succeeds.
- Confirm open-order retrieval succeeds.
- Confirm cancel-order path works on a tiny test order if feasible.

Live startup sequence:

1. Load config.
2. Verify `TRADING_MODE=live`.
3. Verify API key permissions by calling account and order-chance APIs.
4. Load previous positions and open orders.
5. Reconcile local state with Upbit.
6. Start market data collection.
7. Start strategy loop.
8. Start order reconciliation loop.
9. Start health reporting.

## 15. Monitoring And Alerts

Log every decision as structured JSON:

- Timestamp
- Mode
- Market
- Strategy state
- Signal
- Risk decision
- Order request
- Order response
- Fill update
- Balance update
- Error and retry details

Alert on:

- Unhandled exception
- Failed API authentication
- 429 or 418 rate-limit response
- Order rejected by Upbit
- Local risk rejection spike
- Stale market data
- Position mismatch between local state and Upbit
- Daily loss limit hit
- Kill switch activated

Start with console logs and daily CSV/JSON reports. Add Slack, Telegram, email, or another notification channel after the core system is stable.

## 16. Testing Plan

Unit tests:

- Config loading and validation
- Market allowlist validation
- Candle storage deduplication
- Strategy signal generation
- Risk checks
- Decimal sizing
- Paper broker fills
- Order state transitions
- Rate-limit parser

Integration tests:

- SDK client creation without keys for public endpoints
- Authenticated account lookup with test credentials in a controlled environment
- Order test endpoint
- Backtest run on fixture candles
- Paper-trading loop over fixture data

Operational tests:

- Kill switch stops new orders
- Restart reconciles state
- Network timeout retries correctly
- 429 backoff works
- Stale open orders are cancelled

## 17. Step-By-Step Build Milestones

### Milestone 1: Project Foundation

1. Create Python project with `pyproject.toml`.
2. Add dependencies: `upbit-sdk`, `python-dotenv`, `pydantic-settings`, `sqlalchemy` or `sqlite-utils`, `pytest`.
3. Add `.env.example`.
4. Implement config loader.
5. Implement structured logging.
6. Add basic tests.

Exit criteria: app starts, loads config, and tests pass.

### Milestone 2: Upbit Gateway

1. Add SDK client factory.
2. Implement public market list call.
3. Implement ticker and candle fetchers.
4. Implement authenticated account lookup.
5. Implement order test wrapper.
6. Add error handling for SDK exceptions.

Exit criteria: public data works without keys; account lookup works with keys; failures are logged clearly.

### Milestone 3: Storage

1. Add SQLite schema.
2. Implement candle upsert.
3. Implement signal/order/fill repositories.
4. Add migration or schema initialization command.
5. Add tests for duplicate candle handling.

Exit criteria: fetched candles are persisted and reloaded reliably.

### Milestone 4: Backtesting

1. Implement strategy interface.
2. Implement moving-average crossover strategy.
3. Implement backtest engine.
4. Include fees and slippage.
5. Output performance report.
6. Add fixture-based tests.

Exit criteria: can run a deterministic backtest from stored candles.

### Milestone 5: Paper Trading

1. Implement broker interface.
2. Implement paper broker.
3. Implement order manager.
4. Implement risk manager.
5. Run paper-trading loop on live market data.
6. Persist all simulated orders and fills.

Exit criteria: paper trading can run unattended and produce a daily report.

### Milestone 6: Live Trading Preparation

1. Implement Upbit broker.
2. Implement order test path.
3. Implement balance and open-order reconciliation.
4. Add kill switch.
5. Add strict live mode confirmation.
6. Add alerts for failures.

Exit criteria: live mode can verify credentials and run order tests without placing real orders.

### Milestone 7: Limited Live Trading

1. Enable one market only.
2. Set very small max order and exposure.
3. Use conservative polling intervals.
4. Place only one order at a time.
5. Reconcile fills and balances after every order.
6. Review logs manually after each session.

Exit criteria: live trading executes, reconciles, and stops correctly under tiny exposure.

### Milestone 8: Hardening

1. Add WebSocket market data if polling is insufficient.
2. Add private WebSocket order/balance updates.
3. Improve rate-limit tracking with response headers.
4. Add dashboard or CLI status view.
5. Add deployment service file or container.
6. Add backup and restore for the database.

Exit criteria: system can run continuously with observable state and controlled failure behavior.

## 18. Initial Implementation Order

Recommended first coding sequence:

1. `pyproject.toml`
2. `.env.example`
3. `src/trader/config.py`
4. `src/trader/upbit_client.py`
5. `src/trader/market_data/candles.py`
6. `src/trader/storage/`
7. `src/trader/strategy/base.py`
8. `src/trader/strategy/moving_average.py`
9. `src/trader/app/backtest.py`
10. `tests/`

Do not implement live order creation until backtesting and paper trading are complete.

## 19. Security Checklist

- `.env` is ignored by git.
- API keys are never logged.
- Secret key is never printed in exceptions.
- API key has minimum required permission groups.
- Withdrawal permissions are disabled.
- Server IP allowlist is configured.
- Production database backups do not expose secrets.
- Logs do not contain Authorization headers.
- Live mode requires explicit config.
- Kill switch is tested.

## 20. Definition Of Done For Version 1

Version 1 is complete when:

- Public market data collection works.
- Backtesting works on stored candles.
- Paper trading uses the same strategy and risk code as live mode.
- Risk controls prevent oversized or duplicate orders.
- Real order path is implemented but gated behind explicit live mode.
- Order test endpoint succeeds.
- Monitoring logs every signal, risk decision, order, fill, and error.
- Restart reconciliation works.
- Tests cover the core strategy, risk, storage, and broker behavior.

After Version 1, improve strategy quality only after the operational foundation is stable.
