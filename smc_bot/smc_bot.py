from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any

import requests

from smc_engine import Candle, Setup, build_setup


SYMBOLS = tuple(s.strip().upper() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip())
SCAN_SECONDS = max(30, int(os.getenv("SCAN_SECONDS", "60")))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
STATE_PATH = Path(os.getenv("STATE_PATH", "/data/smc_state.json" if Path("/data").exists() else "smc_state.json"))
BINANCE_ENDPOINTS = (
    "https://api.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("smc-bot")
running = True


def stop(*_: Any) -> None:
    global running
    running = False


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"active": {}, "last_signal": {}}


def save_state(state: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except OSError as exc:
        log.warning("Could not persist state: %s", exc)


def fetch_candles(symbol: str, interval: str, limit: int = 200) -> list[Candle]:
    last_error: Exception | None = None
    for endpoint in BINANCE_ENDPOINTS:
        try:
            response = requests.get(endpoint, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
            response.raise_for_status()
            rows = response.json()
            # Ignore the currently forming candle to prevent repainting.
            return [
                Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[6]))
                for r in rows[:-1]
            ]
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            last_error = exc
    raise RuntimeError(f"Binance data unavailable for {symbol} {interval}: {last_error}")


def current_price(symbol: str) -> float:
    return fetch_candles(symbol, "1m", 3)[-1].close


def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.info("Telegram not configured. Alert:\n%s", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
    response.raise_for_status()


def decimals(symbol: str) -> int:
    return 2 if symbol.startswith(("BTC", "ETH")) else 3


def fmt(symbol: str, value: float) -> str:
    return f"{value:.{decimals(symbol)}f}"


def setup_message(setup: Setup) -> str:
    side = "🟢 شراء LONG" if setup.direction == "long" else "🔴 بيع SHORT"
    return (
        "🧠 SMC BOT — إشارة جديدة\n\n"
        f"الزوج: {setup.symbol.replace('USDT', '/USDT')}\n"
        f"الاتجاه: {side}\n"
        f"Entry: {fmt(setup.symbol, setup.entry)}\n"
        f"SL: {fmt(setup.symbol, setup.stop)}\n"
        f"TP1: {fmt(setup.symbol, setup.tp1)}\n"
        f"TP2: {fmt(setup.symbol, setup.tp2)}\n"
        f"TP3: {fmt(setup.symbol, setup.tp3)}\n"
        f"R:R إلى TP3 = 1:{setup.risk_reward:.1f}\n\n"
        "التأكيد: اتجاه الهيكل 1H ✅\n"
        "Liquidity Sweep 15m ✅\n"
        "CHoCH 5m ✅\n"
        "FVG Retest 5m ✅\n\n"
        "إشارة تحليلية وليست أمراً مضموناً للتداول."
    )


def monitor_trade(symbol: str, trade: dict[str, Any], price: float) -> bool:
    direction = trade["direction"]
    hit = lambda level: price >= level if direction == "long" else price <= level
    stopped = price <= trade["stop"] if direction == "long" else price >= trade["stop"]
    if stopped:
        send_telegram(f"🛑 SMC BOT | {symbol} ضرب SL عند {fmt(symbol, price)}")
        return True
    for target in ("tp1", "tp2", "tp3"):
        if not trade.get(f"{target}_hit") and hit(trade[target]):
            trade[f"{target}_hit"] = True
            send_telegram(f"✅ SMC BOT | {symbol} ضرب {target.upper()} عند {fmt(symbol, price)}")
            if target == "tp3":
                return True
    return False


def setup_to_trade(setup: Setup) -> dict[str, Any]:
    return {
        "direction": setup.direction,
        "entry": setup.entry,
        "stop": setup.stop,
        "tp1": setup.tp1,
        "tp2": setup.tp2,
        "tp3": setup.tp3,
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "detected_at": setup.detected_at,
    }


def scan_once(state: dict[str, Any]) -> None:
    for symbol in SYMBOLS:
        try:
            price = current_price(symbol)
            active = state["active"].get(symbol)
            if active:
                if monitor_trade(symbol, active, price):
                    state["active"].pop(symbol, None)
                save_state(state)
                continue

            setup = build_setup(
                symbol,
                fetch_candles(symbol, "1h"),
                fetch_candles(symbol, "15m"),
                fetch_candles(symbol, "5m"),
            )
            if not setup or state["last_signal"].get(symbol) == setup.detected_at:
                continue
            send_telegram(setup_message(setup))
            state["active"][symbol] = setup_to_trade(setup)
            state["last_signal"][symbol] = setup.detected_at
            save_state(state)
        except Exception:
            log.exception("Scan failed for %s", symbol)


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    state = load_state()
    state.setdefault("active", {})
    state.setdefault("last_signal", {})
    log.info("SMC Bot started for %s; SMC-only mode", ", ".join(SYMBOLS))
    while running:
        started = time.monotonic()
        scan_once(state)
        remaining = max(1, SCAN_SECONDS - (time.monotonic() - started))
        end = time.monotonic() + remaining
        while running and time.monotonic() < end:
            time.sleep(min(1, end - time.monotonic()))
    log.info("SMC Bot stopped")


if __name__ == "__main__":
    main()

