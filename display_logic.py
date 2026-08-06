from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Sequence

from models import (
    ANSI_COLORS,
    SPEED_KMH_TO_MPH,
    TEMP_GAUGE_KEYS,
    GaugeSpec,
    GaugeThreshold,
    UnitPreferences,
)


def render_regular_bar(ratio: float, width: int, filled_char: str = "█", empty_char: str = "░") -> str:
    if width <= 0:
        return ""
    ratio = clamp(ratio, 0.0, 1.0)
    filled = int(round(ratio * width))
    filled = max(0, min(width, filled))
    return (filled_char * filled) + (empty_char * (width - filled))


def colorize(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    code = ANSI_COLORS.get(color)
    if not code:
        return text
    return f"{code}{text}{ANSI_COLORS['reset']}"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def segment_level(value: float, threshold: GaugeThreshold) -> str:
    if threshold.direction == "low":
        if threshold.critical is not None and value <= threshold.critical:
            return "critical"
        if threshold.warning is not None and value <= threshold.warning:
            return "warning"
        return "normal"

    if threshold.critical is not None and value >= threshold.critical:
        return "critical"
    if threshold.warning is not None and value >= threshold.warning:
        return "warning"
    return "normal"


def threshold_index(value: Optional[float], minimum: float, maximum: float, width: int) -> Optional[int]:
    if value is None or maximum <= minimum:
        return None
    ratio = clamp((value - minimum) / (maximum - minimum), 0.0, 1.0)
    return int(ratio * (width - 1))


def sparkline(values: Sequence[float], minimum: float, maximum: float, width: int = 22) -> str:
    if not values:
        return " " * width

    blocks = "▁▂▃▄▅▆▇█"
    recent = list(values)[-width:]
    if len(recent) < width:
        recent = [recent[0]] * (width - len(recent)) + recent

    span = maximum - minimum
    if span <= 0:
        return blocks[0] * width

    chars: List[str] = []
    for value in recent:
        ratio = clamp((value - minimum) / span, 0.0, 1.0)
        idx = int(ratio * (len(blocks) - 1))
        chars.append(blocks[idx])
    return "".join(chars)


def threshold_status(value: float, threshold: GaugeThreshold) -> str:
    level = segment_level(value, threshold)
    if level == "critical":
        return "CRIT"
    if level == "warning":
        return "WARN"
    return "OK"


def threshold_step(gauge: GaugeSpec) -> float:
    if gauge.key == "rpm":
        return 100.0
    if gauge.key in {"speed", "coolant_temp", "intake_temp"}:
        return 2.0
    return 1.0


def display_unit_for_gauge(gauge: GaugeSpec, units: UnitPreferences) -> str:
    if gauge.key == "speed":
        return "mph" if units.speed == "mph" else "km/h"
    if gauge.key in TEMP_GAUGE_KEYS:
        return "°F" if units.temperature == "f" else "°C"
    return gauge.unit


def value_to_display(gauge: GaugeSpec, value: float, units: UnitPreferences) -> float:
    if gauge.key == "speed" and units.speed == "mph":
        return value * SPEED_KMH_TO_MPH
    if gauge.key in TEMP_GAUGE_KEYS and units.temperature == "f":
        return (value * 9.0 / 5.0) + 32.0
    return value


def value_from_display(gauge: GaugeSpec, value: float, units: UnitPreferences) -> float:
    if gauge.key == "speed" and units.speed == "mph":
        return value / SPEED_KMH_TO_MPH
    if gauge.key in TEMP_GAUGE_KEYS and units.temperature == "f":
        return (value - 32.0) * 5.0 / 9.0
    return value


def format_gauge_value(gauge: GaugeSpec, value: float, units: UnitPreferences) -> str:
    display_value = value_to_display(gauge, value, units)
    if gauge.key == "speed" and units.speed == "mph":
        return f"{display_value:.0f}"
    if gauge.key in TEMP_GAUGE_KEYS and units.temperature == "f":
        return f"{display_value:.0f}"
    return gauge.formatter.format(display_value)


def format_gauge_offset(gauge: GaugeSpec, delta: float, units: UnitPreferences) -> str:
    display_delta = value_to_display(gauge, delta, units) - value_to_display(gauge, 0.0, units)
    if gauge.key == "speed" and units.speed == "mph":
        return f"{display_delta:+.0f}"
    if gauge.key in TEMP_GAUGE_KEYS and units.temperature == "f":
        return f"{display_delta:+.0f}"
    if gauge.key in {"rpm", "speed"}:
        return f"{display_delta:+.0f}"
    return f"{display_delta:+.1f}"


def threshold_step_base(gauge: GaugeSpec, units: UnitPreferences) -> float:
    if gauge.key == "speed":
        if units.speed == "mph":
            return value_from_display(gauge, 1.0, units)
        return 2.0
    if gauge.key in TEMP_GAUGE_KEYS:
        if units.temperature == "f":
            return value_from_display(gauge, 2.0, units) - value_from_display(gauge, 0.0, units)
        return 2.0
    return threshold_step(gauge)


def toggle_unit_preferences(units: UnitPreferences) -> UnitPreferences:
    speed = "mph" if units.speed == "kmh" else "kmh"
    temperature = "f" if units.temperature == "c" else "c"
    return UnitPreferences(speed=speed, temperature=temperature)


def adjust_threshold(
    threshold: GaugeThreshold,
    gauge: GaugeSpec,
    field: str,
    delta: float,
) -> GaugeThreshold:
    low = gauge.min_value
    high = gauge.max_value
    new_warning = threshold.warning if threshold.warning is not None else low
    new_critical = threshold.critical if threshold.critical is not None else high

    if field == "warning":
        new_warning = clamp(new_warning + delta, low, high)
    else:
        new_critical = clamp(new_critical + delta, low, high)

    if threshold.direction == "high":
        if new_warning > new_critical:
            if field == "warning":
                new_critical = new_warning
            else:
                new_warning = new_critical
    else:
        if new_warning < new_critical:
            if field == "warning":
                new_critical = new_warning
            else:
                new_warning = new_critical

    return replace(threshold, warning=new_warning, critical=new_critical)
