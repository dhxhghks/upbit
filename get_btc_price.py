#!/usr/bin/env python3
"""Fetch the current Bitcoin price from Upbit's public ticker API."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


UPBIT_TICKER_URL = "https://api.upbit.com/v1/ticker"
MARKET = "KRW-BTC"


def fetch_current_price(market: str = MARKET) -> dict:
    """Return the latest Upbit ticker payload for a market such as KRW-BTC."""
    query = urllib.parse.urlencode({"markets": market})
    request = urllib.request.Request(
        f"{UPBIT_TICKER_URL}?{query}",
        headers={"Accept": "application/json"},
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)

    if not payload:
        raise RuntimeError(f"Upbit returned no ticker data for {market}")

    return payload[0]


def main() -> int:
    try:
        ticker = fetch_current_price()
    except urllib.error.HTTPError as error:
        print(f"Upbit API returned HTTP {error.code}: {error.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"Could not connect to Upbit: {error.reason}", file=sys.stderr)
        return 1
    except TimeoutError:
        print("Timed out while connecting to Upbit.", file=sys.stderr)
        return 1

    trade_price = ticker["trade_price"]
    signed_change_rate = ticker["signed_change_rate"] * 100
    signed_change_price = ticker["signed_change_price"]
    fetched_at = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S %Z")

    print(f"Market: {ticker['market']}")
    print(f"Current BTC price: {trade_price:,.0f} KRW")
    print(f"Change: {signed_change_price:,.0f} KRW ({signed_change_rate:+.2f}%)")
    print(f"Fetched at: {fetched_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
