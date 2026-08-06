from __future__ import annotations

import time
from dataclasses import replace
from typing import Dict, List, Sequence

from display_logic import (
    clamp,
    colorize,
    display_unit_for_gauge,
    format_gauge_value,
    render_regular_bar,
    segment_level,
    value_to_display,
)
from models import GaugeSpec, GaugeThreshold, UnitPreferences
from obd_core import GAUGE_SPECS, OBDClient, collect_demo_values, collect_live_values


def render_bar(
    label: str,
    value: float,
    minimum: float,
    maximum: float,
    unit: str,
    threshold: GaugeThreshold,
    width: int = 44,
    use_color: bool = True,
) -> str:
    ratio = clamp((value - minimum) / (maximum - minimum), 0.0, 1.0) if maximum > minimum else 0.0
    value_level = segment_level(value, threshold)
    bar_color = "bright_cyan"
    if value_level == "warning":
        bar_color = "yellow"
    elif value_level == "critical":
        bar_color = "red"
    bar = colorize(render_regular_bar(ratio, width), bar_color, use_color)

    value_color = "bright_cyan"
    if value_level == "warning":
        value_color = "yellow"
    elif value_level == "critical":
        value_color = "red"

    value_text = colorize(f"{value:7.1f}", value_color, use_color)
    threshold_bits: List[str] = []
    if threshold.warning is not None:
        threshold_bits.append(f"warn:{threshold.warning:.0f}")
    if threshold.critical is not None:
        threshold_bits.append(f"crit:{threshold.critical:.0f}")
    threshold_bits.append(f"dir:{threshold.direction}")
    threshold_text = " " + " ".join(threshold_bits) if threshold_bits else ""
    gauge_label = colorize(f"{label:<12}", "bright_magenta", use_color)
    return f"{gauge_label} [ {bar} ] {value_text} {unit}{threshold_text}"


def render_speed_digital_line(
    value: float,
    threshold: GaugeThreshold,
    unit_preferences: UnitPreferences,
    use_color: bool,
) -> str:
    gauge = GAUGE_SPECS["speed"]
    display_value = format_gauge_value(gauge, value, unit_preferences)
    value_level = segment_level(value, threshold)
    value_color = "bright_cyan"
    if value_level == "warning":
        value_color = "yellow"
    elif value_level == "critical":
        value_color = "red"

    label_text = colorize(f"{gauge.label:<12}", "bright_magenta", use_color)
    digital_text = colorize(f"{display_value:>7}", value_color, use_color)
    threshold_bits: List[str] = []
    if threshold.warning is not None:
        threshold_bits.append(f"warn:{format_gauge_value(gauge, threshold.warning, unit_preferences)}")
    if threshold.critical is not None:
        threshold_bits.append(f"crit:{format_gauge_value(gauge, threshold.critical, unit_preferences)}")
    threshold_bits.append(f"dir:{threshold.direction}")
    threshold_text = " " + " ".join(threshold_bits)
    return f"{label_text} {digital_text} {display_unit_for_gauge(gauge, unit_preferences)}{threshold_text}"


def render_dashboard(
    values: Dict[str, float],
    gauges: Sequence[GaugeSpec],
    thresholds: Dict[str, GaugeThreshold],
    unit_preferences: UnitPreferences,
    use_color: bool,
) -> str:
    lines = []
    title = colorize("OBD-II TERMINAL // CYBERPUNK", "bright_cyan", use_color)
    lines.append(colorize(title, "bold", use_color))
    lines.append(colorize("=" * 84, "bright_blue", use_color))
    for gauge in gauges:
        value = values.get(gauge.key, 0.0)
        threshold = thresholds.get(gauge.key, GaugeThreshold())
        if gauge.key == "speed":
            lines.append(render_speed_digital_line(value, threshold, unit_preferences, use_color))
            continue
        warning_value = value_to_display(gauge, threshold.warning, unit_preferences) if threshold.warning is not None else None
        critical_value = value_to_display(gauge, threshold.critical, unit_preferences) if threshold.critical is not None else None
        display_threshold = replace(threshold, warning=warning_value, critical=critical_value)
        lines.append(
            render_bar(
                gauge.label,
                value_to_display(gauge, value, unit_preferences),
                value_to_display(gauge, gauge.min_value, unit_preferences),
                value_to_display(gauge, gauge.max_value, unit_preferences),
                display_unit_for_gauge(gauge, unit_preferences),
                display_threshold,
                use_color=use_color,
            )
        )
    lines.append(colorize("=" * 84, "bright_blue", use_color))
    lines.append(colorize("CTRL+C to quit", "dim", use_color))
    return "\n".join(lines)


def run_demo(
    gauges: Sequence[GaugeSpec],
    thresholds: Dict[str, GaugeThreshold],
    unit_preferences: UnitPreferences,
    interval: float = 0.5,
    use_color: bool = True,
) -> None:
    while True:
        values = collect_demo_values()
        print("\033[2J\033[H" + render_dashboard(values, gauges, thresholds, unit_preferences, use_color), end="", flush=True)
        time.sleep(interval)


def run_live(
    client: OBDClient,
    gauges: Sequence[GaugeSpec],
    thresholds: Dict[str, GaugeThreshold],
    unit_preferences: UnitPreferences,
    interval: float = 0.75,
    use_color: bool = True,
) -> None:
    while True:
        values = collect_live_values(client, gauges)
        print("\033[2J\033[H" + render_dashboard(values, gauges, thresholds, unit_preferences, use_color), end="", flush=True)
        time.sleep(interval)
