#!/usr/bin/env python3
"""Local web dashboard for monitoring Upbit coin status."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.error
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from simple_auto_trader import (
    KST,
    UpbitClient,
    decide_signal,
    load_state,
    make_order,
    split_market,
    load_config,
    save_state,
    validate_config,
)

DEFAULT_WATCHLIST = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
DEFAULT_TRADING_LOG_FILE = Path("state/trading_runs.jsonl")
TOP_VOLUME_LIMIT = 5
SUPPORTED_TRADING_STRATEGIES = {"simple_sma", "watchlist_momentum", "top_volume_momentum"}
TRADING_LOCK = threading.Lock()
TRADING_STOP = threading.Event()
TRADING_THREAD: threading.Thread | None = None
TRADING_STATE: dict[str, Any] = {
    "active": False,
    "interval": 300,
    "config": None,
    "last_result": None,
    "error": "",
    "started_at": "",
    "stopped_at": "",
}

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
      <a href="/trading">Trading</a>
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
        <div class="label" id="signal-detail">-</div>
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
        setText("signal-detail", `${fmtKrw.format(data.strategy.signal_price)} · ${data.strategy.reason}`);

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
      <a href="/trading">Trading</a>
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


TRADING_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Auto Trading</title>
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
    .grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }
    .panel {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }
    .form-panel { grid-column: span 5; }
    .result-panel { grid-column: span 7; }
    .result-panel {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin: 0 0 7px;
    }
    .field { margin-bottom: 13px; }
    select, input, button {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
    }
    input[type="checkbox"] {
      width: 16px;
      min-height: 16px;
      margin: 0 8px 0 0;
      vertical-align: middle;
    }
    .row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .actions {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
    }
    button {
      cursor: pointer;
      background: #22313b;
    }
    button:hover { border-color: var(--blue); }
    button.danger { background: #3b2424; }
    .status-bar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      background: var(--panel-2);
      border-radius: 8px;
      padding: 12px;
    }
    .status {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 0 10px;
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
    }
    .badge.active {
      border-color: var(--green);
      color: var(--green);
    }
    .badge.error {
      border-color: var(--red);
      color: var(--red);
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .summary-card {
      border: 1px solid var(--line);
      background: var(--panel-2);
      border-radius: 8px;
      padding: 12px;
      min-width: 0;
      min-height: 82px;
    }
    .summary-card .label {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .summary-card .value {
      font-size: 20px;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .section-title {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 9px 7px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child { text-align: left; }
    th { color: var(--muted); font-weight: 600; }
    tr:last-child td { border-bottom: 0; }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .empty {
      color: var(--muted);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      line-height: 1.45;
    }
    .history-panel {
      grid-column: span 12;
    }
    .history-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }
    .history-header button {
      width: auto;
      min-width: 92px;
    }
    .history-table td, .history-table th {
      font-size: 13px;
    }
    details {
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    summary {
      cursor: pointer;
      color: var(--muted);
      background: var(--panel-2);
      padding: 10px 12px;
      font-size: 13px;
    }
    pre {
      margin: 0;
      max-height: 320px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--text);
      font-size: 13px;
      line-height: 1.45;
      padding: 12px;
    }
    .positive { color: var(--green); }
    .negative { color: var(--red); }
    .warning { color: var(--amber); }
    @media (max-width: 840px) {
      main { width: min(100vw - 20px, 1180px); padding-top: 14px; }
      header { align-items: stretch; flex-direction: column; }
      h1 { font-size: 23px; }
      .form-panel, .result-panel { grid-column: span 12; }
      .actions, .row { grid-template-columns: 1fr; }
      .summary-grid { grid-template-columns: 1fr; }
      .status-bar { grid-template-columns: 1fr; }
      .history-header { align-items: stretch; flex-direction: column; }
      .history-header button { width: 100%; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Auto Trading</h1>
        <div class="sub" id="updated">Loading trading controls</div>
      </div>
    </header>
    <nav aria-label="Pages">
      <a href="/">Dashboard</a>
      <a href="/watchlist">Watchlist</a>
      <a href="/trading" aria-current="page">Trading</a>
    </nav>

    <section class="grid">
      <form class="panel form-panel" id="trade-form">
        <div class="field">
          <label for="market">Market</label>
          <select id="market" name="market"></select>
        </div>
        <div class="field">
          <label for="strategy">Strategy</label>
          <select id="strategy" name="strategy">
            <option value="simple_sma">Simple SMA Crossover</option>
            <option value="watchlist_momentum">Watchlist Momentum Spike</option>
            <option value="top_volume_momentum">Top Volume Momentum</option>
          </select>
        </div>
        <div class="field">
          <label for="mode">Mode</label>
          <select id="mode" name="mode">
            <option value="paper">Paper</option>
            <option value="test">Test</option>
            <option value="live">Live</option>
          </select>
        </div>
        <div class="row">
          <div class="field">
            <label for="short_sma">Short SMA</label>
            <input id="short_sma" name="short_sma" type="number" min="1" value="5">
          </div>
          <div class="field">
            <label for="long_sma">Long SMA</label>
            <input id="long_sma" name="long_sma" type="number" min="2" value="20">
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="candle_unit">Candle Unit</label>
            <input id="candle_unit" name="candle_unit" type="number" min="1" value="5">
          </div>
          <div class="field">
            <label for="candle_count">Candle Count</label>
            <input id="candle_count" name="candle_count" type="number" min="20" value="60">
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="order_krw">Order KRW</label>
            <input id="order_krw" name="order_krw" type="number" min="0" value="5000">
          </div>
          <div class="field">
            <label for="interval">Loop Interval Seconds</label>
            <input id="interval" name="interval" type="number" min="30" value="300">
          </div>
        </div>
        <div class="row">
          <div class="field">
            <label for="surge_pct">Surge Trigger %</label>
            <input id="surge_pct" name="surge_pct" type="number" min="0" step="0.1" value="1.2">
          </div>
          <div class="field">
            <label for="volume_multiplier">Volume Spike Multiple</label>
            <input id="volume_multiplier" name="volume_multiplier" type="number" min="1" step="0.1" value="2.0">
          </div>
        </div>
        <div class="field">
          <label for="live_confirm_market">Live Confirm Market</label>
          <input id="live_confirm_market" name="live_confirm_market" placeholder="Type selected market for live mode">
        </div>
        <div class="field">
          <label>
            <input id="live_confirm" name="live_confirm" type="checkbox">
            I understand live mode can place real orders
          </label>
        </div>
        <div class="actions">
          <button id="run-once" type="button">Run Once</button>
          <button id="start-loop" type="button">Start Loop</button>
          <button id="stop-loop" class="danger" type="button">Stop</button>
        </div>
      </form>

      <section class="panel result-panel">
        <div class="status-bar">
          <div class="status" id="loop-status">Loop status unavailable</div>
          <div class="badge" id="loop-badge">Stopped</div>
        </div>

        <div class="summary-grid" aria-label="Latest result summary">
          <div class="summary-card">
            <div class="label">Mode</div>
            <div class="value" id="summary-mode">-</div>
          </div>
          <div class="summary-card">
            <div class="label">Signal</div>
            <div class="value" id="summary-signal">-</div>
          </div>
          <div class="summary-card">
            <div class="label">Order Status</div>
            <div class="value" id="summary-order">-</div>
          </div>
          <div class="summary-card">
            <div class="label">Market</div>
            <div class="value" id="summary-market">-</div>
          </div>
          <div class="summary-card">
            <div class="label">Last Price</div>
            <div class="value" id="summary-price">-</div>
          </div>
          <div class="summary-card">
            <div class="label">Updated</div>
            <div class="value" id="summary-updated">-</div>
          </div>
        </div>

        <section>
          <div class="section-title">Execution Detail</div>
          <div id="detail-empty" class="empty">No test result has been recorded yet.</div>
          <div class="table-wrap" id="detail-wrap" hidden>
            <table>
              <tbody id="detail-body"></tbody>
            </table>
          </div>
        </section>

        <section id="candidates-section" hidden>
          <div class="section-title" id="candidates-title">Momentum Candidates</div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Market</th>
                  <th>24h Value</th>
                  <th>Recent %</th>
                  <th>5 Candle %</th>
                  <th>Volume x</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody id="candidates-body"></tbody>
            </table>
          </div>
        </section>

        <details>
          <summary>Raw JSON</summary>
          <pre id="result">{}</pre>
        </details>
      </section>

      <section class="panel history-panel">
        <div class="history-header">
          <div>
            <div class="section-title">Previous Test Runs</div>
            <div class="status" id="history-status">Loading previous runs</div>
          </div>
          <button id="refresh-history" type="button">Refresh</button>
        </div>
        <div id="history-empty" class="empty">No previous runs have been logged yet.</div>
        <div class="table-wrap" id="history-wrap" hidden>
          <table class="history-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Mode</th>
                <th>Strategy</th>
                <th>Market</th>
                <th>Signal</th>
                <th>Price</th>
                <th>Reason</th>
                <th>Order</th>
                <th>Skipped</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody id="history-body"></tbody>
          </table>
        </div>
      </section>
    </section>
  </main>

  <script>
    const form = document.getElementById("trade-form");
    const result = document.getElementById("result");
    const statusEl = document.getElementById("loop-status");
    const badge = document.getElementById("loop-badge");
    const refreshHistory = document.getElementById("refresh-history");
    const fmtKrw = new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 });

    function text(id, value) {
      document.getElementById(id).textContent = value ?? "-";
    }

    function signalClass(signal) {
      if (signal === "buy") return "positive";
      if (signal === "sell") return "negative";
      if (signal === "hold") return "warning";
      return "";
    }

    function formatKrw(value) {
      if (value === null || value === undefined || value === "") return "-";
      return fmtKrw.format(Number(value));
    }

    function orderStatus(data) {
      if (!data) return "-";
      if (data.skipped) return "Skipped";
      if (data.order_result) return data.config?.mode === "paper" ? "Paper filled" : "Accepted";
      if (data.order) return "Created";
      return "No order";
    }

    function signalPrice(data) {
      return data?.signal_price || data?.last_price || data?.decision?.selected_price || data?.decision?.candidates?.[0]?.last_price || "";
    }

    function signalReason(data) {
      return data?.signal_reason || data?.decision?.reason || "";
    }

    function addDetail(label, value, className = "") {
      const row = document.createElement("tr");
      const labelCell = document.createElement("td");
      const valueCell = document.createElement("td");
      labelCell.textContent = label;
      valueCell.textContent = value ?? "-";
      if (className) valueCell.className = className;
      row.append(labelCell, valueCell);
      document.getElementById("detail-body").appendChild(row);
    }

    function showResult(data) {
      show(data);
      const hasResult = data && !data.error && data.updated_at;
      text("summary-mode", data?.config?.mode || "-");
      text("summary-market", data?.config?.market || data?.decision?.market || "-");
      text("summary-price", formatKrw(signalPrice(data)));
      text("summary-updated", data?.updated_at || "-");

      const signal = data?.signal || "-";
      const signalEl = document.getElementById("summary-signal");
      signalEl.textContent = signal === "-" ? "-" : signal.toUpperCase();
      signalEl.className = `value ${signalClass(signal)}`;
      text("summary-order", data?.error ? "Error" : orderStatus(data));

      const detailEmpty = document.getElementById("detail-empty");
      const detailWrap = document.getElementById("detail-wrap");
      const detailBody = document.getElementById("detail-body");
      detailBody.replaceChildren();

      if (hasResult) {
        addDetail("Strategy", data.strategy);
        addDetail("Signal Price", formatKrw(signalPrice(data)));
        addDetail("Signal Reason", signalReason(data) || "-");
        addDetail("Previous Signal", data.previous_signal || "-");
        addDetail("Short SMA", formatKrw(data.short_sma));
        addDetail("Long SMA", formatKrw(data.long_sma));
        addDetail("Skipped", data.skipped ? "Yes" : "No", data.skipped ? "warning" : "");
        addDetail("Skip Reason", data.skip_reason || "-");
        addDetail("Decision Reason", data.decision?.reason || "-");
        addDetail("Order", data.order ? JSON.stringify(data.order) : "-");
        addDetail("Order Result", data.order_result ? JSON.stringify(data.order_result) : "-");
        detailEmpty.hidden = true;
        detailWrap.hidden = false;
      } else {
        detailEmpty.textContent = data?.error || "No test result has been recorded yet.";
        detailEmpty.className = data?.error ? "empty negative" : "empty";
        detailEmpty.hidden = false;
        detailWrap.hidden = true;
      }

      const candidatesSection = document.getElementById("candidates-section");
      document.getElementById("candidates-title").textContent =
        data?.strategy === "top_volume_momentum" ? "Top Volume Momentum Candidates" : "Momentum Candidates";
      const candidatesBody = document.getElementById("candidates-body");
      candidatesBody.replaceChildren();
      const candidates = data?.decision?.candidates || [];
      for (const item of candidates) {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${item.market}</td>
          <td>${formatKrw(item.acc_trade_price_24h)}</td>
          <td class="${signalClass(item.recent_change_pct >= 0 ? "buy" : "sell")}">${Number(item.recent_change_pct).toFixed(2)}%</td>
          <td>${Number(item.five_candle_change_pct).toFixed(2)}%</td>
          <td>${Number(item.volume_multiplier).toFixed(2)}x</td>
          <td>${Number(item.score).toFixed(2)}</td>
        `;
        candidatesBody.appendChild(row);
      }
      candidatesSection.hidden = candidates.length === 0;
    }

    function renderHistory(items) {
      const historyStatus = document.getElementById("history-status");
      const historyEmpty = document.getElementById("history-empty");
      const historyWrap = document.getElementById("history-wrap");
      const historyBody = document.getElementById("history-body");
      historyBody.replaceChildren();

      if (!items.length) {
        historyStatus.textContent = "No saved test runs";
        historyEmpty.hidden = false;
        historyWrap.hidden = true;
        return;
      }

      for (const entry of items) {
        const run = entry.result || {};
        const row = document.createElement("tr");
        const signal = run.signal || "-";
        row.innerHTML = `
          <td>${entry.logged_at || run.updated_at || "-"}</td>
          <td>${run.config?.mode || "-"}</td>
          <td>${run.strategy || "-"}</td>
          <td>${run.config?.market || run.decision?.market || "-"}</td>
          <td class="${signalClass(signal)}">${signal === "-" ? "-" : signal.toUpperCase()}</td>
          <td>${formatKrw(signalPrice(run))}</td>
          <td>${signalReason(run) || "-"}</td>
          <td>${run.error ? "Error" : orderStatus(run)}</td>
          <td>${run.skipped ? "Yes" : "No"}</td>
          <td class="${run.error ? "negative" : ""}">${run.error || "-"}</td>
        `;
        row.addEventListener("click", () => showResult(run));
        historyBody.appendChild(row);
      }

      historyStatus.textContent = `Loaded ${items.length} saved runs`;
      historyEmpty.hidden = true;
      historyWrap.hidden = false;
    }

    async function loadHistory() {
      refreshHistory.disabled = true;
      try {
        const data = await api("/api/trading/logs?limit=50");
        renderHistory(data.items || []);
      } catch (err) {
        document.getElementById("history-status").textContent = "Could not load previous runs";
        document.getElementById("history-empty").hidden = false;
        document.getElementById("history-empty").textContent = err.error || "Trading log request failed";
        document.getElementById("history-wrap").hidden = true;
      } finally {
        refreshHistory.disabled = false;
      }
    }

    function payload() {
      return {
        market: form.market.value,
        strategy: form.strategy.value,
        mode: form.mode.value,
        short_sma: Number(form.short_sma.value),
        long_sma: Number(form.long_sma.value),
        candle_unit: Number(form.candle_unit.value),
        candle_count: Number(form.candle_count.value),
        order_krw: form.order_krw.value,
        interval: Number(form.interval.value),
        surge_pct: form.surge_pct.value,
        volume_multiplier: form.volume_multiplier.value,
        live_confirm: form.live_confirm.checked,
        live_confirm_market: form.live_confirm_market.value.trim()
      };
    }

    function show(data) {
      result.textContent = JSON.stringify(data, null, 2);
    }

    async function api(path, body = null) {
      const options = body ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      } : { cache: "no-store" };
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok) throw data;
      return data;
    }

    async function loadOptions() {
      const data = await api("/api/trading/options");
      const market = document.getElementById("market");
      market.replaceChildren();
      for (const item of data.watchlist) {
        const option = document.createElement("option");
        option.value = item;
        option.textContent = item;
        market.appendChild(option);
      }
      form.market.value = data.config.market;
      form.mode.value = data.config.mode;
      form.short_sma.value = data.config.short_sma;
      form.long_sma.value = data.config.long_sma;
      form.candle_unit.value = data.config.candle_unit;
      form.candle_count.value = data.config.candle_count;
      form.order_krw.value = data.config.order_krw;
      form.surge_pct.value = data.config.surge_pct;
      form.volume_multiplier.value = data.config.volume_multiplier;
      document.getElementById("updated").textContent = `Loaded ${data.updated_at}`;
    }

    async function refreshState() {
      const state = await api("/api/trading/state");
      badge.textContent = state.error ? "Error" : state.active ? "Running" : "Stopped";
      badge.className = `badge ${state.error ? "error" : state.active ? "active" : ""}`;
      statusEl.textContent = state.error
        ? `Last run failed: ${state.error}`
        : state.active
          ? `Loop running every ${state.interval}s for ${state.config?.market || "-"} in ${state.config?.mode || "-"} mode`
          : state.stopped_at
            ? `Loop stopped at ${state.stopped_at}`
            : "Loop stopped";
      if (state.last_result) showResult(state.last_result);
    }

    document.getElementById("run-once").addEventListener("click", async () => {
      try {
        showResult(await api("/api/trading/run", payload()));
        await refreshState();
        await loadHistory();
      } catch (err) {
        showResult(err);
      }
    });

    document.getElementById("start-loop").addEventListener("click", async () => {
      try {
        show(await api("/api/trading/start", payload()));
        await refreshState();
      } catch (err) {
        showResult(err);
      }
    });

    document.getElementById("stop-loop").addEventListener("click", async () => {
      try {
        show(await api("/api/trading/stop", {}));
        await refreshState();
        await loadHistory();
      } catch (err) {
        showResult(err);
      }
    });

    refreshHistory.addEventListener("click", loadHistory);

    form.market.addEventListener("change", () => {
      form.live_confirm_market.value = "";
    });

    loadOptions().then(refreshState).then(loadHistory).catch(show);
    setInterval(refreshState, 5000);
    setInterval(loadHistory, 30000);
  </script>
</body>
</html>
"""


def to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Could not parse decimal value {value!r}") from exc


def decimal_json(value: Decimal | int | float | str) -> int | float:
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def optional_decimal_json(value: Decimal | int | float | str | None) -> int | float | None:
    if value is None:
        return None
    return decimal_json(value)


def load_watchlist() -> list[str]:
    configured = os.environ.get("WATCHLIST", "")
    markets = [market.strip().upper() for market in configured.split(",") if market.strip()]
    return markets or DEFAULT_WATCHLIST


def fetch_tickers(client: UpbitClient, markets: list[str]) -> list[dict[str, Any]]:
    tickers: list[dict[str, Any]] = []
    for index in range(0, len(markets), 100):
        batch = markets[index : index + 100]
        if batch:
            tickers.extend(client.public_get("/v1/ticker", {"markets": ",".join(batch)}))
    return tickers


def list_quote_markets(client: UpbitClient, quote: str = "KRW") -> list[str]:
    prefix = f"{quote.upper()}-"
    markets = client.public_get("/v1/market/all", {"is_details": "false"})
    return sorted(str(item["market"]) for item in markets if str(item.get("market", "")).startswith(prefix))


def top_volume_markets(client: UpbitClient, quote: str = "KRW", limit: int = TOP_VOLUME_LIMIT) -> list[dict[str, Any]]:
    markets = list_quote_markets(client, quote)
    tickers = fetch_tickers(client, markets)
    ranked = sorted(
        tickers,
        key=lambda ticker: to_decimal(ticker.get("acc_trade_price_24h", "0")),
        reverse=True,
    )
    return [
        {
            "market": str(ticker["market"]),
            "trade_price": to_decimal(ticker["trade_price"]),
            "acc_trade_price_24h": to_decimal(ticker.get("acc_trade_price_24h", "0")),
            "signed_change_rate": to_decimal(ticker.get("signed_change_rate", "0")),
        }
        for ticker in ranked[:limit]
    ]


def build_watchlist() -> dict[str, Any]:
    config = load_config()
    client = UpbitClient(config)
    markets = load_watchlist()
    tickers = fetch_tickers(client, markets)

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
    signal, short_sma, long_sma, reason = decide_signal(closes, config.short_sma, config.long_sma)

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
            "signal_price": decimal_json(closes[-1]),
            "reason": reason,
            "short_sma": decimal_json(short_sma),
            "long_sma": decimal_json(long_sma),
            "last_candle_at": str(candles[0].get("candle_date_time_kst", "")),
        },
        "accounts": accounts,
    }


def clean_int(value: Any, default: int) -> int:
    if value in {None, ""}:
        return default
    return int(value)


def clean_decimal(value: Any, default: Decimal) -> Decimal:
    if value in {None, ""}:
        return default
    return to_decimal(value)


def trading_options() -> dict[str, Any]:
    config = load_config()
    watchlist = load_watchlist()
    if config.market not in watchlist:
        watchlist = [config.market, *watchlist]
    return {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "watchlist": watchlist,
        "strategies": [
            {"id": "simple_sma", "name": "Simple SMA Crossover"},
            {"id": "watchlist_momentum", "name": "Watchlist Momentum Spike"},
            {"id": "top_volume_momentum", "name": "Top Volume Momentum"},
        ],
        "modes": ["paper", "test", "live"],
        "config": {
            "market": config.market,
            "mode": config.mode,
            "candle_unit": config.candle_unit,
            "candle_count": config.candle_count,
            "short_sma": config.short_sma,
            "long_sma": config.long_sma,
            "order_krw": str(config.order_krw),
            "surge_pct": os.environ.get("MOMENTUM_SURGE_PCT", "1.2"),
            "volume_multiplier": os.environ.get("MOMENTUM_VOLUME_MULTIPLIER", "2.0"),
        },
    }


def trading_config_from_payload(payload: dict[str, Any]) -> Any:
    base = load_config()
    strategy = str(payload.get("strategy", "simple_sma"))
    if strategy not in SUPPORTED_TRADING_STRATEGIES:
        raise ValueError(f"Unsupported strategy: {strategy}")

    market = str(payload.get("market") or base.market).strip().upper()
    mode = str(payload.get("mode") or base.mode).strip().lower()
    live_confirm = bool(payload.get("live_confirm"))
    live_confirm_market = str(payload.get("live_confirm_market", "")).strip().upper()

    if mode == "live":
        if not live_confirm:
            raise RuntimeError("Live mode requires checking the live confirmation box.")
        if live_confirm_market != market:
            raise RuntimeError("Live mode requires typing the selected market exactly.")

    values = {
        **base.__dict__,
        "market": market,
        "mode": mode,
        "candle_unit": clean_int(payload.get("candle_unit"), base.candle_unit),
        "candle_count": clean_int(payload.get("candle_count"), base.candle_count),
        "short_sma": clean_int(payload.get("short_sma"), base.short_sma),
        "long_sma": clean_int(payload.get("long_sma"), base.long_sma),
        "order_krw": clean_decimal(payload.get("order_krw"), base.order_krw),
        "allow_live_trading": base.allow_live_trading and live_confirm,
        "confirm_live_market": live_confirm_market if mode == "live" else base.confirm_live_market,
    }
    config = base.__class__(**values)
    validate_config(config)
    return config


def trading_strategy_from_payload(payload: dict[str, Any]) -> str:
    strategy = str(payload.get("strategy", "simple_sma"))
    if strategy not in SUPPORTED_TRADING_STRATEGIES:
        raise ValueError(f"Unsupported strategy: {strategy}")
    return strategy


def momentum_settings_from_payload(payload: dict[str, Any]) -> dict[str, Decimal]:
    return {
        "surge_pct": clean_decimal(
            payload.get("surge_pct"),
            to_decimal(os.environ.get("MOMENTUM_SURGE_PCT", "1.2")),
        ),
        "volume_multiplier": clean_decimal(
            payload.get("volume_multiplier"),
            to_decimal(os.environ.get("MOMENTUM_VOLUME_MULTIPLIER", "2.0")),
        ),
    }


def config_summary(config: Any) -> dict[str, Any]:
    return {
        "market": config.market,
        "mode": config.mode,
        "candle_unit": config.candle_unit,
        "candle_count": config.candle_count,
        "short_sma": config.short_sma,
        "long_sma": config.long_sma,
        "order_krw": str(config.order_krw),
    }


def decide_momentum_from_markets(
    client: UpbitClient,
    config: Any,
    settings: dict[str, Decimal],
    markets: list[str],
    source_metrics: dict[str, dict[str, Any]] | None = None,
    universe_label: str = "watchlist",
) -> dict[str, Any]:
    candidates = []
    source_metrics = source_metrics or {}
    for market in markets:
        market_config = config.__class__(**{**config.__dict__, "market": market})
        candles = client.public_get(
            f"/v1/candles/minutes/{market_config.candle_unit}",
            {"market": market, "count": max(market_config.candle_count, 20)},
        )
        ordered = list(reversed(candles))
        closes = [to_decimal(candle["trade_price"]) for candle in ordered]
        values = [to_decimal(candle.get("candle_acc_trade_price", "0")) for candle in ordered]
        if len(closes) < 6 or len(values) < 6:
            continue

        recent_change_pct = (closes[-1] - closes[-2]) / closes[-2] * Decimal("100")
        five_candle_change_pct = (closes[-1] - closes[-6]) / closes[-6] * Decimal("100")
        baseline_volume = sum(values[-6:-1]) / Decimal("5")
        current_volume = values[-1]
        volume_multiplier = current_volume / baseline_volume if baseline_volume > 0 else Decimal("0")
        score = recent_change_pct + five_candle_change_pct + volume_multiplier

        candidates.append(
            {
                "market": market,
                "last_price": closes[-1],
                "recent_change_pct": recent_change_pct,
                "five_candle_change_pct": five_candle_change_pct,
                "current_volume": current_volume,
                "baseline_volume": baseline_volume,
                "volume_multiplier": volume_multiplier,
                "score": score,
                "acc_trade_price_24h": source_metrics.get(market, {}).get("acc_trade_price_24h"),
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    top = candidates[0] if candidates else None
    signal = "hold"
    reason = f"No {universe_label} candle data was available."
    selected_market = config.market
    if top:
        selected_market = str(top["market"])
        surge_hit = top["recent_change_pct"] >= settings["surge_pct"]
        volume_hit = top["volume_multiplier"] >= settings["volume_multiplier"]
        if surge_hit and volume_hit:
            signal = "buy"
            reason = f"Leading {universe_label} met both price surge and volume spike thresholds."
        elif top["recent_change_pct"] < Decimal("0"):
            signal = "sell"
            reason = f"Leading {universe_label} momentum turned negative."
        else:
            reason = f"No {universe_label} met both aggressive buy thresholds."

    return {
        "signal": signal,
        "market": selected_market,
        "selected_price": decimal_json(top["last_price"]) if top else None,
        "reason": reason,
        "settings": {key: decimal_json(value) for key, value in settings.items()},
        "candidates": [
            {
                "market": item["market"],
                "last_price": decimal_json(item["last_price"]),
                "recent_change_pct": float(item["recent_change_pct"]),
                "five_candle_change_pct": float(item["five_candle_change_pct"]),
                "current_volume": decimal_json(item["current_volume"]),
                "baseline_volume": decimal_json(item["baseline_volume"]),
                "volume_multiplier": float(item["volume_multiplier"]),
                "acc_trade_price_24h": optional_decimal_json(item.get("acc_trade_price_24h")),
                "score": float(item["score"]),
            }
            for item in candidates[:10]
        ],
    }


def decide_watchlist_momentum(
    client: UpbitClient,
    config: Any,
    settings: dict[str, Decimal],
) -> dict[str, Any]:
    return decide_momentum_from_markets(client, config, settings, load_watchlist(), universe_label="watchlist market")


def decide_top_volume_momentum(
    client: UpbitClient,
    config: Any,
    settings: dict[str, Decimal],
) -> dict[str, Any]:
    top_markets = top_volume_markets(client, "KRW", TOP_VOLUME_LIMIT)
    markets = [item["market"] for item in top_markets]
    source_metrics = {item["market"]: item for item in top_markets}
    decision = decide_momentum_from_markets(
        client,
        config,
        settings,
        markets,
        source_metrics,
        "top-volume market",
    )
    decision["top_volume_markets"] = [
        {
            "rank": index + 1,
            "market": item["market"],
            "trade_price": decimal_json(item["trade_price"]),
            "acc_trade_price_24h": decimal_json(item["acc_trade_price_24h"]),
            "signed_change_rate": float(item["signed_change_rate"]),
        }
        for index, item in enumerate(top_markets)
    ]
    return decision


def run_trading_cycle(config: Any) -> dict[str, Any]:
    client = UpbitClient(config)
    candles = client.get_candles()
    closes = [to_decimal(candle["trade_price"]) for candle in reversed(candles)]
    last_price = closes[-1]
    signal, short_sma, long_sma, reason = decide_signal(closes, config.short_sma, config.long_sma)

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    signal_key = f"{config.mode}:{config.market}"
    state = load_state(config.state_file)
    signals = state.setdefault("signals", {})
    previous_signal = signals.get(signal_key)

    result: dict[str, Any] = {
        "updated_at": now,
        "config": config_summary(config),
        "strategy": "simple_sma",
        "last_price": decimal_json(last_price),
        "signal_price": decimal_json(last_price),
        "signal_reason": reason,
        "short_sma": decimal_json(short_sma),
        "long_sma": decimal_json(long_sma),
        "signal": signal,
        "previous_signal": previous_signal,
        "skipped": False,
        "skip_reason": "",
        "order": None,
        "order_result": None,
    }

    if signal == previous_signal:
        result["skipped"] = True
        result["skip_reason"] = "Signal has not changed since the previous cycle."
        return result

    accounts = client.get_accounts() if config.mode in {"test", "live"} else None
    order = make_order(config, signal, accounts)
    result["order"] = order

    signals[signal_key] = signal
    state["updated_at"] = now

    if order is None:
        result["skipped"] = True
        result["skip_reason"] = "No order was created for this signal."
        save_state(config.state_file, state)
        return result

    order_result = client.place_order(order)
    result["order_result"] = order_result
    state.setdefault("last_orders", {})[signal_key] = order
    save_state(config.state_file, state)
    return result


def run_watchlist_momentum_cycle(config: Any, settings: dict[str, Decimal]) -> dict[str, Any]:
    client = UpbitClient(config)
    decision = decide_watchlist_momentum(client, config, settings)
    selected_config = config.__class__(**{**config.__dict__, "market": decision["market"]})
    signal = str(decision["signal"])
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    signal_key = f"{selected_config.mode}:watchlist_momentum:{selected_config.market}"

    state = load_state(selected_config.state_file)
    signals = state.setdefault("signals", {})
    previous_signal = signals.get(signal_key)
    result: dict[str, Any] = {
        "updated_at": now,
        "config": config_summary(selected_config),
        "strategy": "watchlist_momentum",
        "signal": signal,
        "signal_price": decision.get("selected_price"),
        "signal_reason": decision.get("reason"),
        "previous_signal": previous_signal,
        "decision": decision,
        "skipped": False,
        "skip_reason": "",
        "order": None,
        "order_result": None,
    }

    if signal == previous_signal:
        result["skipped"] = True
        result["skip_reason"] = "Signal has not changed since the previous cycle for the selected market."
        return result

    accounts = client.get_accounts() if selected_config.mode in {"test", "live"} else None
    order = make_order(selected_config, signal, accounts)
    result["order"] = order

    signals[signal_key] = signal
    state["updated_at"] = now

    if order is None:
        result["skipped"] = True
        result["skip_reason"] = "No order was created for this signal."
        save_state(selected_config.state_file, state)
        return result

    result["order_result"] = client.place_order(order)
    state.setdefault("last_orders", {})[signal_key] = order
    save_state(selected_config.state_file, state)
    return result


def run_top_volume_momentum_cycle(config: Any, settings: dict[str, Decimal]) -> dict[str, Any]:
    client = UpbitClient(config)
    decision = decide_top_volume_momentum(client, config, settings)
    selected_config = config.__class__(**{**config.__dict__, "market": decision["market"]})
    signal = str(decision["signal"])
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    signal_key = f"{selected_config.mode}:top_volume_momentum:{selected_config.market}"

    state = load_state(selected_config.state_file)
    signals = state.setdefault("signals", {})
    previous_signal = signals.get(signal_key)
    result: dict[str, Any] = {
        "updated_at": now,
        "config": config_summary(selected_config),
        "strategy": "top_volume_momentum",
        "signal": signal,
        "signal_price": decision.get("selected_price"),
        "signal_reason": decision.get("reason"),
        "previous_signal": previous_signal,
        "decision": decision,
        "skipped": False,
        "skip_reason": "",
        "order": None,
        "order_result": None,
    }

    if signal == previous_signal:
        result["skipped"] = True
        result["skip_reason"] = "Signal has not changed since the previous cycle for the selected top-volume market."
        return result

    accounts = client.get_accounts() if selected_config.mode in {"test", "live"} else None
    order = make_order(selected_config, signal, accounts)
    result["order"] = order

    signals[signal_key] = signal
    state["updated_at"] = now

    if order is None:
        result["skipped"] = True
        result["skip_reason"] = "No order was created for this signal."
        save_state(selected_config.state_file, state)
        return result

    result["order_result"] = client.place_order(order)
    state.setdefault("last_orders", {})[signal_key] = order
    save_state(selected_config.state_file, state)
    return result


def trading_state_payload() -> dict[str, Any]:
    with TRADING_LOCK:
        return dict(TRADING_STATE)


def trading_log_path() -> Path:
    configured = os.environ.get("TRADING_LOG_FILE", "").strip()
    return Path(configured) if configured else DEFAULT_TRADING_LOG_FILE


def append_trading_log(result: dict[str, Any], source: str) -> None:
    entry = {
        "logged_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "source": source,
        "result": result,
    }
    path = trading_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        file.write("\n")


def safe_append_trading_log(result: dict[str, Any], source: str) -> None:
    try:
        append_trading_log(result, source)
    except Exception as exc:
        print(f"Could not write trading log: {exc}", file=sys.stderr)


def read_trading_logs(limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    path = trading_log_path()
    if not path.exists():
        return {
            "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
            "path": str(path),
            "items": [],
        }

    lines = path.read_text(encoding="utf-8").splitlines()
    items: list[dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            items.append(entry)
        if len(items) >= limit:
            break

    return {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "path": str(path),
        "items": items,
    }


def trading_worker(config: Any, interval: int) -> None:
    strategy = str(TRADING_STATE.get("strategy", "simple_sma"))
    settings = {
        key: to_decimal(value)
        for key, value in dict(TRADING_STATE.get("settings") or {}).items()
    }
    while not TRADING_STOP.is_set():
        try:
            if strategy == "watchlist_momentum":
                result = run_watchlist_momentum_cycle(config, settings)
            elif strategy == "top_volume_momentum":
                result = run_top_volume_momentum_cycle(config, settings)
            else:
                result = run_trading_cycle(config)
        except Exception as exc:
            result = {
                "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                "config": config_summary(config),
                "strategy": strategy,
                "signal": "",
                "skipped": False,
                "order": None,
                "order_result": None,
                "error": str(exc),
            }
            safe_append_trading_log(result, "loop")
            with TRADING_LOCK:
                TRADING_STATE["error"] = str(exc)
                TRADING_STATE["last_result"] = result
        else:
            safe_append_trading_log(result, "loop")
            with TRADING_LOCK:
                TRADING_STATE["last_result"] = result
                TRADING_STATE["error"] = ""
        TRADING_STOP.wait(interval)

    with TRADING_LOCK:
        TRADING_STATE["active"] = False
        TRADING_STATE["stopped_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")


def start_trading_loop(payload: dict[str, Any]) -> dict[str, Any]:
    global TRADING_THREAD
    interval = max(clean_int(payload.get("interval"), 300), 30)
    config = trading_config_from_payload(payload)
    strategy = trading_strategy_from_payload(payload)
    settings = momentum_settings_from_payload(payload)

    with TRADING_LOCK:
        if TRADING_STATE["active"]:
            raise RuntimeError("Trading loop is already running.")
        TRADING_STOP.clear()
        TRADING_STATE.update(
            {
                "active": True,
                "interval": interval,
                "config": config_summary(config),
                "strategy": strategy,
                "settings": {key: decimal_json(value) for key, value in settings.items()},
                "last_result": None,
                "error": "",
                "started_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                "stopped_at": "",
            }
        )
        TRADING_THREAD = threading.Thread(target=trading_worker, args=(config, interval), daemon=True)
        TRADING_THREAD.start()

    return trading_state_payload()


def stop_trading_loop() -> dict[str, Any]:
    TRADING_STOP.set()
    thread = TRADING_THREAD
    if thread and thread.is_alive():
        thread.join(timeout=5)
    with TRADING_LOCK:
        TRADING_STATE["active"] = False
        TRADING_STATE["stopped_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    return trading_state_payload()


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
        if parsed.path == "/trading":
            self._send_html(TRADING_HTML)
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
        if parsed.path == "/api/trading/options":
            try:
                payload = trading_options()
            except (ValueError, RuntimeError, urllib.error.URLError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            except Exception as exc:
                self._send_json({"error": f"Unexpected server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                self._send_json(payload)
            return
        if parsed.path == "/api/trading/state":
            self._send_json(trading_state_payload())
            return
        if parsed.path == "/api/trading/logs":
            params = parse_qs(parsed.query)
            try:
                limit = int(params.get("limit", ["50"])[0])
                payload = read_trading_logs(limit)
            except (ValueError, RuntimeError, urllib.error.URLError) as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            except Exception as exc:
                self._send_json({"error": f"Unexpected server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                self._send_json(payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload: dict[str, Any] = {}
        try:
            payload = self._read_json()
            if parsed.path == "/api/trading/run":
                config = trading_config_from_payload(payload)
                strategy = trading_strategy_from_payload(payload)
                if strategy == "watchlist_momentum":
                    result = run_watchlist_momentum_cycle(config, momentum_settings_from_payload(payload))
                elif strategy == "top_volume_momentum":
                    result = run_top_volume_momentum_cycle(config, momentum_settings_from_payload(payload))
                else:
                    result = run_trading_cycle(config)
                safe_append_trading_log(result, "run_once")
                with TRADING_LOCK:
                    TRADING_STATE["last_result"] = result
                    TRADING_STATE["error"] = ""
                self._send_json(result)
                return
            if parsed.path == "/api/trading/start":
                self._send_json(start_trading_loop(payload))
                return
            if parsed.path == "/api/trading/stop":
                self._send_json(stop_trading_loop())
                return
        except (ValueError, RuntimeError, urllib.error.URLError) as exc:
            if parsed.path == "/api/trading/run":
                safe_append_trading_log(
                    {
                        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "config": {
                            "market": str(payload.get("market", "")),
                            "mode": str(payload.get("mode", "")),
                        },
                        "strategy": str(payload.get("strategy", "")),
                        "signal": "",
                        "skipped": False,
                        "order": None,
                        "order_result": None,
                        "error": str(exc),
                    },
                    "run_once",
                )
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_json({"error": f"Unexpected server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
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

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        data = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("JSON request body must be an object.")
        return parsed

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
