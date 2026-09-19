from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    close_time: int


@dataclass(frozen=True)
class FVG:
    direction: str
    low: float
    high: float
    created_at: int

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


@dataclass(frozen=True)
class Setup:
    symbol: str
    direction: str
    bias: str
    sweep_level: float
    sweep_extreme: float
    choch_level: float
    fvg: FVG
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    detected_at: int

    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry - self.stop)
        return abs(self.tp3 - self.entry) / risk if risk else 0.0


def _pivot_highs(candles: list[Candle], left: int = 2, right: int = 2) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for i in range(left, len(candles) - right):
        value = candles[i].high
        if all(value > candles[j].high for j in range(i - left, i)) and all(
            value >= candles[j].high for j in range(i + 1, i + right + 1)
        ):
            points.append((i, value))
    return points


def _pivot_lows(candles: list[Candle], left: int = 2, right: int = 2) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for i in range(left, len(candles) - right):
        value = candles[i].low
        if all(value < candles[j].low for j in range(i - left, i)) and all(
            value <= candles[j].low for j in range(i + 1, i + right + 1)
        ):
            points.append((i, value))
    return points


def market_structure_bias(candles: Iterable[Candle]) -> str:
    data = list(candles)
    highs = _pivot_highs(data)
    lows = _pivot_lows(data)
    if len(highs) < 2 or len(lows) < 2:
        return "neutral"

    higher_high = highs[-1][1] > highs[-2][1]
    higher_low = lows[-1][1] > lows[-2][1]
    lower_high = highs[-1][1] < highs[-2][1]
    lower_low = lows[-1][1] < lows[-2][1]
    if higher_high and higher_low:
        return "bullish"
    if lower_high and lower_low:
        return "bearish"
    return "neutral"


def find_recent_sweep(candles: list[Candle], lookback: int = 20, recent: int = 8) -> Optional[dict]:
    # Only closed candles are supplied. A sweep must take liquidity and close back inside.
    start = max(lookback, len(candles) - recent)
    found: Optional[dict] = None
    for i in range(start, len(candles)):
        history = candles[i - lookback : i]
        old_low = min(c.low for c in history)
        old_high = max(c.high for c in history)
        candle = candles[i]
        if candle.low < old_low and candle.close > old_low:
            found = {
                "direction": "long",
                "index": i,
                "time": candle.open_time,
                "level": old_low,
                "extreme": candle.low,
            }
        elif candle.high > old_high and candle.close < old_high:
            found = {
                "direction": "short",
                "index": i,
                "time": candle.open_time,
                "level": old_high,
                "extreme": candle.high,
            }
    return found


def _last_structure_level_before(candles: list[Candle], before_time: int, direction: str) -> Optional[float]:
    eligible = [c for c in candles if c.open_time < before_time]
    if direction == "long":
        pivots = _pivot_highs(eligible)
    else:
        pivots = _pivot_lows(eligible)
    return pivots[-1][1] if pivots else None


def _find_choch(candles: list[Candle], after_time: int, direction: str, level: float) -> Optional[int]:
    for i, candle in enumerate(candles):
        if candle.open_time <= after_time:
            continue
        if direction == "long" and candle.close > level:
            return i
        if direction == "short" and candle.close < level:
            return i
    return None


def _find_fvg_after(candles: list[Candle], start_index: int, direction: str) -> Optional[FVG]:
    latest: Optional[FVG] = None
    for i in range(max(2, start_index), len(candles) - 1):
        first, third = candles[i - 2], candles[i]
        if direction == "long" and third.low > first.high:
            latest = FVG("long", first.high, third.low, third.open_time)
        elif direction == "short" and third.high < first.low:
            latest = FVG("short", third.high, first.low, third.open_time)
    return latest


def _touches_fvg(candle: Candle, fvg: FVG) -> bool:
    # Paper entry is the FVG midpoint; require an actual midpoint fill.
    return candle.low <= fvg.midpoint <= candle.high


def build_setup(symbol: str, h1: list[Candle], m15: list[Candle], m5: list[Candle]) -> Optional[Setup]:
    bias = market_structure_bias(h1)
    if bias == "neutral" or len(m15) < 30 or len(m5) < 40:
        return None

    sweep = find_recent_sweep(m15)
    if not sweep:
        return None
    expected = "long" if bias == "bullish" else "short"
    if sweep["direction"] != expected:
        return None

    choch_level = _last_structure_level_before(m5, sweep["time"], expected)
    if choch_level is None:
        return None
    choch_index = _find_choch(m5, sweep["time"], expected, choch_level)
    if choch_index is None:
        return None

    fvg = _find_fvg_after(m5, choch_index, expected)
    if fvg is None or not _touches_fvg(m5[-1], fvg):
        return None

    entry = fvg.midpoint
    buffer = entry * 0.0005
    if expected == "long":
        stop = min(sweep["extreme"], fvg.low) - buffer
        risk = entry - stop
        if risk <= 0:
            return None
        tp1, tp2, tp3 = entry + risk, entry + 2 * risk, entry + 3 * risk
    else:
        stop = max(sweep["extreme"], fvg.high) + buffer
        risk = stop - entry
        if risk <= 0:
            return None
        tp1, tp2, tp3 = entry - risk, entry - 2 * risk, entry - 3 * risk

    return Setup(
        symbol=symbol,
        direction=expected,
        bias=bias,
        sweep_level=sweep["level"],
        sweep_extreme=sweep["extreme"],
        choch_level=choch_level,
        fvg=fvg,
        entry=entry,
        stop=stop,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        detected_at=m5[-1].close_time,
    )
