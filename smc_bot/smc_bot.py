from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import requests

from smc_engine import Candle, Setup, build_setup


SYMBOLS = tuple(s.strip().upper() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",") if s.strip())
SCAN_SECONDS = max(30, int(os.getenv("SCAN_SECONDS", "60")))
REPORT_SECONDS = max(3600, int(os.getenv("REPORT_SECONDS", "7200")))
INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "5000"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_TOTAL_RISK = float(os.getenv("MAX_TOTAL_RISK", "0.03"))
MAX_NOTIONAL_MULTIPLIER = float(os.getenv("MAX_NOTIONAL_MULTIPLIER", "2"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
STATE_PATH = Path(os.getenv("STATE_PATH", "/data/smc_state.json" if Path("/data").exists() else "smc_state.json"))
BINANCE_ENDPOINTS = (
    "https://api.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
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


def ensure_portfolio(state: dict[str, Any]) -> dict[str, Any]:
    portfolio = state.setdefault(
        "portfolio",
        {
            "initial_balance": INITIAL_BALANCE,
            "balance": INITIAL_BALANCE,
            "realized_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "closed_trades": 0,
            "peak_balance": INITIAL_BALANCE,
            "max_drawdown_pct": 0.0,
            "started_at": int(time.time()),
        },
    )
    state.setdefault("next_report_at", int(time.time()) + REPORT_SECONDS)
    return portfolio


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
        "🧠 SMC | صفقة تجريبية جديدة\n\n"
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
        "المحفظة: Paper Trading وليست أموالاً حقيقية."
    )


def close_trade(state: dict[str, Any], symbol: str, trade: dict[str, Any], exit_price: float, result: str) -> None:
    portfolio = ensure_portfolio(state)
    multiplier = 1 if trade["direction"] == "long" else -1
    pnl = (exit_price - trade["entry"]) * trade["quantity"] * multiplier
    portfolio["balance"] += pnl
    portfolio["realized_pnl"] += pnl
    portfolio["closed_trades"] += 1
    if pnl >= 0:
        portfolio["wins"] += 1
    else:
        portfolio["losses"] += 1
    portfolio["peak_balance"] = max(portfolio["peak_balance"], portfolio["balance"])
    drawdown = (portfolio["peak_balance"] - portfolio["balance"]) / portfolio["peak_balance"] * 100
    portfolio["max_drawdown_pct"] = max(portfolio["max_drawdown_pct"], drawdown)
    send_telegram(
        f"🧠 SMC | إغلاق {symbol}\n"
        f"النتيجة: {result}\n"
        f"P/L: {pnl:+.2f}$\n"
        f"الرصيد: {portfolio['balance']:.2f}$"
    )


def monitor_trade(state: dict[str, Any], symbol: str, trade: dict[str, Any], price: float) -> bool:
    direction = trade["direction"]
    hit = lambda level: price >= level if direction == "long" else price <= level
    stopped = price <= trade["stop"] if direction == "long" else price >= trade["stop"]
    if stopped:
        close_trade(state, symbol, trade, trade["stop"], "🛑 SL")
        return True
    for target in ("tp1", "tp2", "tp3"):
        if not trade.get(f"{target}_hit") and hit(trade[target]):
            trade[f"{target}_hit"] = True
            send_telegram(f"🧠 SMC | {symbol} ضرب {target.upper()} عند {fmt(symbol, price)}")
            if target == "tp3":
                close_trade(state, symbol, trade, trade["tp3"], "✅ TP3")
                return True
    return False


def setup_to_trade(state: dict[str, Any], setup: Setup) -> dict[str, Any] | None:
    portfolio = ensure_portfolio(state)
    open_risk = sum(float(t.get("risk_usd", 0)) for t in state["active"].values())
    risk_budget = portfolio["balance"] * RISK_PER_TRADE
    available_risk = max(0.0, portfolio["balance"] * MAX_TOTAL_RISK - open_risk)
    planned_risk = min(risk_budget, available_risk)
    stop_distance = abs(setup.entry - setup.stop)
    if planned_risk <= 0 or stop_distance <= 0:
        return None
    quantity = planned_risk / stop_distance
    max_notional = portfolio["balance"] * MAX_NOTIONAL_MULTIPLIER
    quantity = min(quantity, max_notional / setup.entry)
    actual_risk = quantity * stop_distance
    if actual_risk < 1:
        return None
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
        "quantity": quantity,
        "notional": quantity * setup.entry,
        "risk_usd": actual_risk,
    }


def report_message(state: dict[str, Any]) -> str:
    portfolio = ensure_portfolio(state)
    unrealized = 0.0
    lines = []
    for symbol, trade in state["active"].items():
        try:
            price = current_price(symbol)
            multiplier = 1 if trade["direction"] == "long" else -1
            pnl = (price - trade["entry"]) * trade["quantity"] * multiplier
            unrealized += pnl
            side = "LONG" if trade["direction"] == "long" else "SHORT"
            lines.append(f"• {symbol} {side}: {pnl:+.2f}$")
        except Exception:
            lines.append(f"• {symbol}: تعذر تحديث السعر")
    closed = portfolio["closed_trades"]
    win_rate = portfolio["wins"] / closed * 100 if closed else 0.0
    equity = portfolio["balance"] + unrealized
    open_text = "\n".join(lines) if lines else "لا توجد صفقات مفتوحة"
    return (
        "🧠 SMC | تقرير الساعتين\n\n"
        f"الرصيد: {portfolio['balance']:.2f}$\n"
        f"Equity: {equity:.2f}$\n"
        f"الربح المحقق: {portfolio['realized_pnl']:+.2f}$\n"
        f"الربح العائم: {unrealized:+.2f}$\n"
        f"الصفقات المغلقة: {closed}\n"
        f"النجاح: {win_rate:.1f}% ({portfolio['wins']}W/{portfolio['losses']}L)\n"
        f"أقصى تراجع: {portfolio['max_drawdown_pct']:.2f}%\n\n"
        f"الصفقات الحالية:\n{open_text}"
    )


def scan_once(state: dict[str, Any]) -> None:
    completed = 0
    for symbol in SYMBOLS:
        try:
            price = current_price(symbol)
            active = state["active"].get(symbol)
            if active:
                if monitor_trade(state, symbol, active, price):
                    state["active"].pop(symbol, None)
                save_state(state)
            else:
                setup = build_setup(
                    symbol,
                    fetch_candles(symbol, "1h"),
                    fetch_candles(symbol, "15m"),
                    fetch_candles(symbol, "5m"),
                )
                if setup and state["last_signal"].get(symbol) != setup.detected_at:
                    trade = setup_to_trade(state, setup)
                    if trade:
                        send_telegram(
                            setup_message(setup)
                            + f"\n\nالمخاطرة: {trade['risk_usd']:.2f}$"
                            + f"\nالحجم الافتراضي: {trade['notional']:.2f}$"
                        )
                        state["active"][symbol] = trade
                        state["last_signal"][symbol] = setup.detected_at
                        save_state(state)
        except Exception:
            log.exception("Scan failed for %s", symbol)
        else:
            completed += 1
    log.info("SMC scan cycle complete: %s/%s symbols", completed, len(SYMBOLS))


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    state = load_state()
    state.setdefault("active", {})
    state.setdefault("last_signal", {})
    ensure_portfolio(state)
    save_state(state)
    log.info("SMC Bot started for %s; SMC-only mode", ", ".join(SYMBOLS))
    send_telegram(
        "🧠 SMC | تم تشغيل المحفظة التجريبية\n"
        f"رأس المال: {INITIAL_BALANCE:.2f}$\n"
        f"المخاطرة لكل صفقة: {RISK_PER_TRADE * 100:.1f}%\n"
        f"أقصى مخاطرة مفتوحة: {MAX_TOTAL_RISK * 100:.1f}%"
    )
    while running:
        started = time.monotonic()
        scan_once(state)
        if time.time() >= state["next_report_at"]:
            send_telegram(report_message(state))
            state["next_report_at"] = int(time.time()) + REPORT_SECONDS
            save_state(state)
        remaining = max(1, SCAN_SECONDS - (time.monotonic() - started))
        end = time.monotonic() + remaining
        while running and time.monotonic() < end:
            time.sleep(min(1, end - time.monotonic()))
    log.info("SMC Bot stopped")


if __name__ == "__main__":
    main()
