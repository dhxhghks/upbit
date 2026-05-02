#!/usr/bin/env python3
"""Local web dashboard for monitoring Upbit coin status."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from simple_auto_trader import (
    KST,
    UpbitClient,
    decide_signal,
    load_config,
    validate_config,
)

DEFAULT_WATCHLIST = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Coin Status Monitor</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101417;
      --panel: #171d21;
      --panel-2: #1f272b;
      --line: #324047;
      --text: #eef3f4;
      --muted: #9cacb2;
      --green: #35c889;
      --red: #ff6767;
      --amber: #f6bc45;
      --blue: #5aa7ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }
    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
      margin-bottom: 18px;
    }
    h1 { margin: 0; font-size: 28px; line-height: 1.1; letter-spacing: 0; }
    .sub { margin-top: 7px; color: var(--muted); font-size: 14px; }
    .controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    nav { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
    nav a {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 6px;
      padding: 8px 12px;
      text-decoration: none;
      font-size: 14px;
    }
    nav a[aria-current="page"] { border-color: var(--blue); color: #d9ecff; }
    select, button {
      min-height: 38px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 6px;
      padding: 0 12px;
      font: inherit;
    }
    button {
      cursor: pointer;
      background: #22313b;
      color: var(--text);
    }
    button:hover { border-color: var(--blue); }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .metric, .wide-panel {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }
    .metric { grid-column: span 3; min-height: 118px; }
    .wide-panel { grid-column: span 6; }
    .account-panel { grid-column: span 12; overflow-x: auto; }
    .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .value {
      font-size: 27px;
      line-height: 1.15;
      overflow-wrap: anywhere;
      letter-spacing: 0;
    }
    .value.small { font-size: 18px; }
    .positive { color: var(--green); }
    .negative { color: var(--red); }
    .hold { color: var(--amber); }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      padding: 11px 8px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child { text-align: left; }
    th { color: var(--muted); font-weight: 600; }
    tr:last-child td { border-bottom: 0; }
    .empty, .error {
      color: var(--muted);
      padding: 14px 0 4px;
      line-height: 1.45;
    }
    .error { color: var(--red); }
    @media (max-width: 880px) {
      header { align-items: stretch; flex-direction: column; }
      .controls { align-items: stretch; }
      select, button { flex: 1 1 140px; }
      .metric { grid-column: span 6; }
      .wide-panel { grid-column: span 12; }
    }
    @media (max-width: 560px) {
      main { width: min(100vw - 20px, 1180px); padding-top: 14px; }
      h1 { font-size: 23px; }
      .metric { grid-column: span 12; }
      .value { font-size: 23px; }
      th, td { padding: 9px 5px; font-size: 12px; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Coin Status Monitor</h1>
        <div class="sub" id="updated">Loading market status</div>
      </div>
      <div class="controls">
        <select id="market" aria-label="Market">
          <option>KRW-BTC</option>
          <option>KRW-ETH</option>
          <option>KRW-XRP</option>
          <option>KRW-SOL</option>
          <option>KRW-DOGE</option>
        </select>
        <button id="refresh" type="button">Refresh</button>
      </div>
    </header>
    <nav aria-label="Pages">
      <a href="/" aria-current="page">Dashboard</a>
      <a href="/watchlist">Watchlist</a>
    </nav>

    <section class="grid">
      <div class="metric">
        <div class="label">Last Price</div>
        <div class="value" id="last-price">-</div>
      </div>
      <div class="metric">
        <div class="label">24h Change</div>
        <div class="value" id="change">-</div>
      </div>
      <div class="metric">
        <div class="label">Strategy Signal</div>
        <div class="value" id="signal">-</div>
      </div>
      <div class="metric">
        <div class="label">Candle Unit</div>
        <div class="value" id="candle-unit">-</div>
      </div>

      <div class="wide-panel">
        <div class="label">Moving Averages</div>
        <table>
          <tbody>
            <tr><td>Short SMA</td><td id="short-sma">-</td></tr>
            <tr><td>Long SMA</td><td id="long-sma">-</td></tr>
            <tr><td>Last Candle</td><td id="last-candle">-</td></tr>
          </tbody>
        </table>
      </div>

      <div class="wide-panel account-panel">
        <div class="label">Account Balances</div>
        <div id="account-error" class="empty">Loading balances</div>
        <table id="accounts-table" hidden>
          <thead>
            <tr>
              <th>Currency</th>
              <th>Balance</th>
              <th>Avg Buy (KRW)</th>
              <th>Current Value (KRW)</th>
              <th>Buy Value (KRW)</th>
              <th>Gain / Loss (KRW)</th>
              <th>Yield</th>
            </tr>
          </thead>
          <tbody id="accounts-body"></tbody>
        </table>
      </div>
    </section>
  </main>

  <script>
    const fmtKrw = new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 });
    const fmtKrwNumber = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
    const fmtNum = new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 });
    const market = document.getElementById("market");
    const refresh = document.getElementById("refresh");

    function setText(id, value) {
      document.getElementById(id).textContent = value;
    }

    function signalClass(signal) {
      if (signal === "buy") return "positive";
      if (signal === "sell") return "negative";
      return "hold";
    }

    function formatKrwOrDash(value) {
      if (value === null || value === undefined || value === "") return "-";
      return fmtKrwNumber.format(Number(value));
    }

    function formatYield(value) {
      if (value === null || value === undefined || value === "") return "-";
      return `${Number(value).toFixed(2)}%`;
    }

    function valueClass(value) {
      if (value === null || value === undefined || value === "" || Number(value) === 0) return "";
      return Number(value) > 0 ? "positive" : "negative";
    }

    async function loadStatus() {
      refresh.disabled = true;
      try {
        const res = await fetch(`/api/status?market=${encodeURIComponent(market.value)}`, { cache: "no-store" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Status request failed");

        setText("updated", `Updated ${data.updated_at} · ${data.market}`);
        setText("last-price", fmtKrw.format(data.ticker.trade_price));

        const rate = data.ticker.signed_change_rate * 100;
        const change = document.getElementById("change");
        change.textContent = `${fmtKrw.format(data.ticker.signed_change_price)} (${rate.toFixed(2)}%)`;
        change.className = `value ${rate >= 0 ? "positive" : "negative"}`;

        const signal = document.getElementById("signal");
        signal.textContent = data.strategy.signal.toUpperCase();
        signal.className = `value ${signalClass(data.strategy.signal)}`;

        setText("candle-unit", `${data.config.candle_unit} min`);
        setText("short-sma", fmtKrw.format(data.strategy.short_sma));
        setText("long-sma", fmtKrw.format(data.strategy.long_sma));
        setText("last-candle", data.strategy.last_candle_at);

        const msg = document.getElementById("account-error");
        const table = document.getElementById("accounts-table");
        const body = document.getElementById("accounts-body");
        body.replaceChildren();

        if (data.accounts.available) {
          for (const account of data.accounts.items) {
            const row = document.createElement("tr");
            row.innerHTML = `
              <td>${account.currency}</td>
              <td>${fmtNum.format(Number(account.balance))}</td>
              <td>${formatKrwOrDash(account.avg_buy_price)}</td>
              <td>${formatKrwOrDash(account.current_value)}</td>
              <td>${formatKrwOrDash(account.buy_value)}</td>
              <td class="${valueClass(account.valuation_gain_loss)}">${formatKrwOrDash(account.valuation_gain_loss)}</td>
              <td class="${valueClass(account.yield)}">${formatYield(account.yield)}</td>
            `;
            body.appendChild(row);
          }
          msg.hidden = true;
          table.hidden = false;
        } else {
          table.hidden = true;
          msg.hidden = false;
          msg.className = data.accounts.error ? "error" : "empty";
          msg.textContent = data.accounts.error || "Set UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY to monitor account balances.";
        }
      } catch (err) {
        setText("updated", "Status request failed");
        document.getElementById("account-error").hidden = false;
        document.getElementById("account-error").className = "error";
        document.getElementById("account-error").textContent = err.message;
      } finally {
        refresh.disabled = false;
      }
    }

    refresh.addEventListener("click", loadStatus);
    market.addEventListener("change", loadStatus);
    loadStatus();
    setInterval(loadStatus, 30000);
  </script>
</body>
</html>
"""


WATCHLIST_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Watchlist</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101417;
      --panel: #171d21;
      --panel-2: #1f272b;
      --line: #324047;
      --text: #eef3f4;
      --muted: #9cacb2;
      --green: #35c889;
      --red: #ff6767;
      --blue: #5aa7ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }
    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
      margin-bottom: 18px;
    }
    h1 { margin: 0; font-size: 28px; line-height: 1.1; letter-spacing: 0; }
    .sub { margin-top: 7px; color: var(--muted); font-size: 14px; }
    nav { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
    nav a {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 6px;
      padding: 8px 12px;
      text-decoration: none;
      font-size: 14px;
    }
    nav a[aria-current="page"] { border-color: var(--blue); color: #d9ecff; }
    button {
      min-height: 38px;
      border: 1px solid var(--line);
      background: #22313b;
      color: var(--text);
      border-radius: 6px;
      padding: 0 12px;
      font: inherit;
      cursor: pointer;
    }
    button:hover { border-color: var(--blue); }
    .panel {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 16px;
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      padding: 11px 8px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child { text-align: left; }
    th { color: var(--muted); font-weight: 600; }
    tr:last-child td { border-bottom: 0; }
    .positive { color: var(--green); }
    .negative { color: var(--red); }
    .empty, .error {
      color: var(--muted);
      padding: 14px 0 4px;
      line-height: 1.45;
    }
    .error { color: var(--red); }
    @media (max-width: 700px) {
      main { width: min(100vw - 20px, 1180px); padding-top: 14px; }
      header { align-items: stretch; flex-direction: column; }
      h1 { font-size: 23px; }
      th, td { padding: 9px 5px; font-size: 12px; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Watchlist</h1>
        <div class="sub" id="updated">Loading watchlist</div>
      </div>
      <button id="refresh" type="button">Refresh</button>
    </header>
    <nav aria-label="Pages">
      <a href="/">Dashboard</a>
      <a href="/watchlist" aria-current="page">Watchlist</a>
    </nav>

    <section class="panel">
      <div id="watchlist-error" class="empty">Loading markets</div>
      <table id="watchlist-table" hidden>
        <thead>
          <tr>
            <th>Market</th>
            <th>Price (KRW)</th>
            <th>Change (KRW)</th>
            <th>Change %</th>
            <th>24h Volume</th>
            <th>High (KRW)</th>
            <th>Low (KRW)</th>
          </tr>
        </thead>
        <tbody id="watchlist-body"></tbody>
      </table>
    </section>
  </main>

  <script>
    const fmtKrwNumber = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
    const fmtNum = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
    const refresh = document.getElementById("refresh");

    function valueClass(value) {
      if (Number(value) === 0) return "";
      return Number(value) > 0 ? "positive" : "negative";
    }

    async function loadWatchlist() {
      refresh.disabled = true;
      try {
        const res = await fetch("/api/watchlist", { cache: "no-store" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Watchlist request failed");

        document.getElementById("updated").textContent = `Updated ${data.updated_at}`;
        const msg = document.getElementById("watchlist-error");
        const table = document.getElementById("watchlist-table");
        const body = document.getElementById("watchlist-body");
        body.replaceChildren();

        for (const item of data.items) {
          const changeRate = item.signed_change_rate * 100;
          const row = document.createElement("tr");
          row.innerHTML = `
            <td>${item.market}</td>
            <td>${fmtKrwNumber.format(item.trade_price)}</td>
            <td class="${valueClass(item.signed_change_price)}">${fmtKrwNumber.format(item.signed_change_price)}</td>
            <td class="${valueClass(changeRate)}">${changeRate.toFixed(2)}%</td>
            <td>${fmtNum.format(item.acc_trade_price_24h)}</td>
            <td>${fmtKrwNumber.format(item.high_price)}</td>
            <td>${fmtKrwNumber.format(item.low_price)}</td>
          `;
          body.appendChild(row);
        }

        msg.hidden = true;
        table.hidden = false;
      } catch (err) {
        document.getElementById("updated").textContent = "Watchlist request failed";
        document.getElementById("watchlist-table").hidden = true;
        const msg = document.getElementById("watchlist-error");
        msg.hidden = false;
        msg.className = "error";
        msg.textContent = err.message;
      } finally {
        refresh.disabled = false;
      }
    }

    refresh.addEventListener("click", loadWatchlist);
    loadWatchlist();
    setInterval(loadWatchlist, 30000);
  </script>
</body>
</html>
"""


def to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Could not parse decimal value {value!r}") from exc


def decimal_json(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def optional_decimal_json(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return decimal_json(value)


def load_watchlist() -> list[str]:
    configured = os.environ.get("WATCHLIST", "")
    markets = [market.strip().upper() for market in configured.split(",") if market.strip()]
    return markets or DEFAULT_WATCHLIST


def build_watchlist() -> dict[str, Any]:
    config = load_config()
    client = UpbitClient(config)
    markets = load_watchlist()
    tickers = client.public_get("/v1/ticker", {"markets": ",".join(markets)})

    by_market = {str(ticker["market"]): ticker for ticker in tickers}
    items = []
    for market in markets:
        ticker = by_market.get(market)
        if not ticker:
            continue
        items.append(
            {
                "market": market,
                "trade_price": decimal_json(to_decimal(ticker["trade_price"])),
                "signed_change_price": decimal_json(to_decimal(ticker["signed_change_price"])),
                "signed_change_rate": float(ticker["signed_change_rate"]),
                "acc_trade_price_24h": decimal_json(to_decimal(ticker.get("acc_trade_price_24h", "0"))),
                "high_price": decimal_json(to_decimal(ticker["high_price"])),
                "low_price": decimal_json(to_decimal(ticker["low_price"])),
            }
        )

    return {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "markets": markets,
        "items": items,
    }


def get_krw_prices(client: UpbitClient, accounts: list[dict[str, Any]]) -> dict[str, Decimal]:
    prices = {"KRW": Decimal("1")}
    currencies = sorted(
        {
            str(account.get("currency", ""))
            for account in accounts
            if account.get("currency") and account.get("currency") != "KRW"
        }
    )

    for currency in currencies:
        try:
            ticker = client.public_get("/v1/ticker", {"markets": f"KRW-{currency}"})[0]
        except Exception:
            continue
        prices[currency] = to_decimal(ticker["trade_price"])

    return prices


def account_payload(account: dict[str, Any], prices: dict[str, Decimal]) -> dict[str, Any]:
    currency = str(account.get("currency", ""))
    balance = to_decimal(account.get("balance", "0"))
    avg_buy_price = to_decimal(account.get("avg_buy_price", "0"))
    current_price = prices.get(currency)

    current_value = balance * current_price if current_price is not None else None
    buy_value = balance * avg_buy_price if avg_buy_price > 0 else None
    valuation_gain_loss = None
    yield_rate = None
    if current_value is not None and buy_value is not None and buy_value > 0:
        valuation_gain_loss = current_value - buy_value
        yield_rate = valuation_gain_loss / buy_value * Decimal("100")

    return {
        "currency": currency,
        "balance": str(account.get("balance", "0")),
        "avg_buy_price": optional_decimal_json(avg_buy_price) if avg_buy_price > 0 else None,
        "current_value": optional_decimal_json(current_value),
        "buy_value": optional_decimal_json(buy_value),
        "valuation_gain_loss": optional_decimal_json(valuation_gain_loss),
        "yield": float(yield_rate) if yield_rate is not None else None,
    }


def build_status(market: str | None = None) -> dict[str, Any]:
    config = load_config()
    if market:
        config = config.__class__(**{**config.__dict__, "market": market})
    validate_config(config)

    client = UpbitClient(config)
    ticker = client.public_get("/v1/ticker", {"markets": config.market})[0]
    candles = client.get_candles()
    closes = [to_decimal(candle["trade_price"]) for candle in reversed(candles)]
    signal, short_sma, long_sma = decide_signal(closes, config.short_sma, config.long_sma)

    accounts: dict[str, Any] = {"available": False, "items": [], "error": ""}
    if config.access_key and config.secret_key:
        try:
            raw_accounts = client.get_accounts()
            prices = get_krw_prices(client, raw_accounts)
            items = [account_payload(account, prices) for account in raw_accounts]
        except Exception as exc:
            accounts["error"] = str(exc)
        else:
            accounts = {"available": True, "items": items, "error": ""}

    return {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "market": config.market,
        "config": {
            "mode": config.mode,
            "candle_unit": config.candle_unit,
            "candle_count": config.candle_count,
            "short_sma": config.short_sma,
            "long_sma": config.long_sma,
        },
        "ticker": {
            "trade_price": decimal_json(to_decimal(ticker["trade_price"])),
            "signed_change_price": decimal_json(to_decimal(ticker["signed_change_price"])),
            "signed_change_rate": float(ticker["signed_change_rate"]),
            "acc_trade_price_24h": decimal_json(to_decimal(ticker.get("acc_trade_price_24h", "0"))),
        },
        "strategy": {
            "signal": signal,
            "short_sma": decimal_json(short_sma),
            "long_sma": decimal_json(long_sma),
            "last_candle_at": str(candles[0].get("candle_date_time_kst", "")),
        },
        "accounts": accounts,
    }


class CoinStatusHandler(BaseHTTPRequestHandler):
    server_version = "CoinStatusWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML)
            return
        if parsed.path == "/watchlist":
            self._send_html(WATCHLIST_HTML)
            return
        if parsed.path == "/api/status":
            params = parse_qs(parsed.query)
            market = params.get("market", [None])[0]
            try:
                payload = build_status(market)
            except (ValueError, RuntimeError, urllib.error.URLError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            except Exception as exc:
                self._send_json({"error": f"Unexpected server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                self._send_json(payload)
            return
        if parsed.path == "/api/watchlist":
            try:
                payload = build_watchlist()
            except (ValueError, RuntimeError, urllib.error.URLError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            except Exception as exc:
                self._send_json({"error": f"Unexpected server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                self._send_json(payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {format % args}", file=sys.stderr)

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Upbit coin status web app.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), CoinStatusHandler)
    print(f"Coin status monitor running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
