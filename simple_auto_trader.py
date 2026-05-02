#!/usr/bin/env python3
"""Small guarded Upbit auto-trader using a simple SMA strategy.

Default mode is paper trading. Real orders require explicit live settings.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Config:
    access_key: str
    secret_key: str
    mode: str
    allow_live_trading: bool
    confirm_live_market: str
    base_url: str
    market: str
    candle_unit: int
    candle_count: int
    short_sma: int
    long_sma: int
    order_krw: Decimal
    min_krw_balance: Decimal
    sell_ratio: Decimal
    state_file: Path


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()
            if not name or name in os.environ:
                continue

            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[name] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, str(default))
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def env_decimal(name: str, default: str) -> Decimal:
    value = os.environ.get(name, default)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal number, got {value!r}") from exc


def load_config() -> Config:
    load_env_file()
    return Config(
        access_key=os.environ.get("UPBIT_ACCESS_KEY", ""),
        secret_key=os.environ.get("UPBIT_SECRET_KEY", ""),
        mode=os.environ.get("TRADING_MODE", "paper").strip().lower(),
        allow_live_trading=env_bool("ALLOW_LIVE_TRADING"),
        confirm_live_market=os.environ.get("CONFIRM_LIVE_MARKET", ""),
        base_url=os.environ.get("UPBIT_BASE_URL", "https://api.upbit.com").rstrip("/"),
        market=os.environ.get("MARKET", "KRW-BTC"),
        candle_unit=env_int("CANDLE_UNIT", 5),
        candle_count=env_int("CANDLE_COUNT", 60),
        short_sma=env_int("SHORT_SMA", 5),
        long_sma=env_int("LONG_SMA", 20),
        order_krw=env_decimal("ORDER_KRW", "5000"),
        min_krw_balance=env_decimal("MIN_KRW_BALANCE", "10000"),
        sell_ratio=env_decimal("SELL_RATIO", "1.0"),
        state_file=Path(os.environ.get("STATE_FILE", "state/trader_state.json")),
    )


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_query_string(params: dict[str, Any]) -> str:
    return urllib.parse.unquote(urllib.parse.urlencode(params, doseq=True))


def create_jwt(access_key: str, secret_key: str, query_string: str = "") -> str:
    header = {"alg": "HS512", "typ": "JWT"}
    payload: dict[str, Any] = {"access_key": access_key, "nonce": str(uuid.uuid4())}

    if query_string:
        payload["query_hash"] = hashlib.sha512(query_string.encode("utf-8")).hexdigest()
        payload["query_hash_alg"] = "SHA512"

    signing_input = ".".join(
        [
            b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha512,
    ).digest()
    return f"{signing_input}.{b64url(signature)}"


class UpbitClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def public_get(self, path: str, params: dict[str, Any]) -> Any:
        query = urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(
            f"{self.config.base_url}{path}?{query}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        return self._send(request)

    def private_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._require_keys()
        params = params or {}
        query_string = build_query_string(params)
        url = f"{self.config.base_url}{path}"
        if query_string:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"

        token = create_jwt(self.config.access_key, self.config.secret_key, query_string)
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            method="GET",
        )
        return self._send(request)

    def private_post(self, path: str, body: dict[str, Any]) -> Any:
        self._require_keys()
        query_string = build_query_string(body)
        token = create_jwt(self.config.access_key, self.config.secret_key, query_string)
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.base_url}{path}",
            data=data,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._send(request)

    def get_candles(self) -> list[dict[str, Any]]:
        return self.public_get(
            f"/v1/candles/minutes/{self.config.candle_unit}",
            {"market": self.config.market, "count": self.config.candle_count},
        )

    def get_accounts(self) -> list[dict[str, Any]]:
        return self.private_get("/v1/accounts")

    def place_order(self, order: dict[str, str]) -> Any:
        if self.config.mode == "test":
            return self.private_post("/v1/orders/test", order)
        if self.config.mode == "live":
            return self.private_post("/v1/orders", order)
        return {"paper": True, "order": order}

    def _require_keys(self) -> None:
        if not self.config.access_key or not self.config.secret_key:
            raise RuntimeError("UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY are required for this mode")

    @staticmethod
    def _send(request: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Upbit HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not connect to Upbit: {exc.reason}") from exc

        return json.loads(body) if body else None


def decimal_from_account(account: dict[str, Any], key: str) -> Decimal:
    return Decimal(str(account.get(key, "0")))


def moving_average(values: list[Decimal], length: int) -> Decimal:
    if len(values) < length:
        raise ValueError(f"Need at least {length} values for SMA")
    window = values[-length:]
    return sum(window) / Decimal(length)


def decide_signal(closes: list[Decimal], short_length: int, long_length: int) -> tuple[str, Decimal, Decimal]:
    short = moving_average(closes, short_length)
    long = moving_average(closes, long_length)
    if short > long:
        return "buy", short, long
    if short < long:
        return "sell", short, long
    return "hold", short, long


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)
        file.write("\n")


def split_market(market: str) -> tuple[str, str]:
    quote, base = market.split("-", 1)
    return quote, base


def find_balance(accounts: list[dict[str, Any]], currency: str) -> Decimal:
    for account in accounts:
        if account.get("currency") == currency:
            return decimal_from_account(account, "balance")
    return Decimal("0")


def make_order(config: Config, signal: str, accounts: list[dict[str, Any]] | None) -> dict[str, str] | None:
    quote, base = split_market(config.market)
    if signal == "buy":
        if accounts is not None:
            quote_balance = find_balance(accounts, quote)
            if quote_balance - config.order_krw < config.min_krw_balance:
                print(
                    f"Skip buy: {quote} balance {quote_balance:,.0f} would go below "
                    f"MIN_KRW_BALANCE {config.min_krw_balance:,.0f}."
                )
                return None
        return {
            "market": config.market,
            "side": "bid",
            "price": str(config.order_krw),
            "ord_type": "price",
        }

    if signal == "sell":
        if accounts is None:
            print("Paper sell signal: no account lookup in paper mode, so no sell volume is calculated.")
            return None

        base_balance = find_balance(accounts, base)
        sell_volume = base_balance * config.sell_ratio
        if sell_volume <= 0:
            print(f"Skip sell: no {base} balance.")
            return None
        return {
            "market": config.market,
            "side": "ask",
            "volume": format(sell_volume.normalize(), "f"),
            "ord_type": "market",
        }

    return None


def validate_config(config: Config) -> None:
    if config.mode not in {"paper", "test", "live"}:
        raise ValueError("TRADING_MODE must be paper, test, or live")
    if config.short_sma <= 0 or config.long_sma <= 0:
        raise ValueError("SHORT_SMA and LONG_SMA must be positive")
    if config.short_sma >= config.long_sma:
        raise ValueError("SHORT_SMA must be smaller than LONG_SMA")
    if config.candle_count < config.long_sma:
        raise ValueError("CANDLE_COUNT must be at least LONG_SMA")
    if not Decimal("0") < config.sell_ratio <= Decimal("1"):
        raise ValueError("SELL_RATIO must be greater than 0 and less than or equal to 1")

    if config.mode == "live":
        if not config.allow_live_trading:
            raise RuntimeError("Live mode blocked: set ALLOW_LIVE_TRADING=true")
        if config.confirm_live_market != config.market:
            raise RuntimeError("Live mode blocked: CONFIRM_LIVE_MARKET must equal MARKET")


def run_once(config: Config) -> None:
    validate_config(config)
    client = UpbitClient(config)

    candles = client.get_candles()
    closes = [Decimal(str(candle["trade_price"])) for candle in reversed(candles)]
    last_price = closes[-1]
    signal, short, long = decide_signal(closes, config.short_sma, config.long_sma)

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{now}] {config.market} last={last_price:,.0f} short_sma={short:,.2f} long_sma={long:,.2f}")
    print(f"Signal: {signal.upper()} mode={config.mode}")

    state = load_state(config.state_file)
    signal_key = f"{config.mode}:{config.market}"
    signals = state.setdefault("signals", {})
    previous_signal = signals.get(signal_key)
    if signal == previous_signal:
        print(f"Skip: signal is still {signal.upper()}, so no repeated order is sent.")
        return

    accounts = None
    if config.mode in {"test", "live"}:
        accounts = client.get_accounts()

    order = make_order(config, signal, accounts)
    if order is None:
        signals[signal_key] = signal
        state["updated_at"] = now
        save_state(config.state_file, state)
        return

    result = client.place_order(order)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    signals[signal_key] = signal
    state.setdefault("last_orders", {})[signal_key] = order
    state["updated_at"] = now
    save_state(config.state_file, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a simple guarded Upbit auto-trader.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="Run one strategy cycle.")
    group.add_argument("--loop", action="store_true", help="Run continuously.")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between loop cycles.")
    args = parser.parse_args()

    config = load_config()

    try:
        if args.loop:
            while True:
                run_once(config)
                time.sleep(args.interval)
        else:
            run_once(config)
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
