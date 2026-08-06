from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, Optional

from models import DEFAULT_THRESHOLDS, DEFAULT_UNIT_PREFERENCES, GaugeThreshold, UnitPreferences
from obd_core import GAUGE_SPECS


def clamp_zoom(value: float) -> float:
    return max(0.7, min(3.0, value))


def load_dashboard_config(config_path: str) -> Dict[str, GaugeThreshold]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key in GAUGE_SPECS:
        if key not in thresholds:
            thresholds[key] = GaugeThreshold()
    path = Path(config_path)

    if not path.exists():
        return thresholds

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Unable to read config file '{config_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Config root must be a JSON object")

    gauges = data.get("gauges", {})
    if not isinstance(gauges, dict):
        raise RuntimeError("Config key 'gauges' must be a JSON object")

    for key, settings in gauges.items():
        if key not in GAUGE_SPECS:
            continue
        if not isinstance(settings, dict):
            continue

        default_threshold = DEFAULT_THRESHOLDS.get(key, GaugeThreshold())

        warning_raw = settings.get("warning")
        critical_raw = settings.get("critical")
        direction_raw = settings.get("direction")

        warning = float(warning_raw) if warning_raw is not None else default_threshold.warning
        critical = float(critical_raw) if critical_raw is not None else default_threshold.critical
        direction = default_threshold.direction
        if isinstance(direction_raw, str) and direction_raw.lower() in {"high", "low"}:
            direction = direction_raw.lower()
        thresholds[key] = GaugeThreshold(warning=warning, critical=critical, direction=direction)

    return thresholds


def load_unit_preferences(config_path: str) -> UnitPreferences:
    path = Path(config_path)
    units = replace(DEFAULT_UNIT_PREFERENCES)
    if not path.exists():
        return units

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Unable to read config file '{config_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Config root must be a JSON object")

    unit_data = data.get("units", {})
    if not isinstance(unit_data, dict):
        return units

    speed = unit_data.get("speed")
    temperature = unit_data.get("temperature")

    if isinstance(speed, str) and speed.lower() in {"kmh", "mph"}:
        units.speed = speed.lower()
    if isinstance(temperature, str) and temperature.lower() in {"c", "f"}:
        units.temperature = temperature.lower()
    return units


def load_display_zoom(config_path: str) -> float:
    path = Path(config_path)
    if not path.exists():
        return 1.0

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Unable to read config file '{config_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Config root must be a JSON object")

    display_data = data.get("display", {})
    if not isinstance(display_data, dict):
        return 1.0

    zoom_raw = display_data.get("zoom", 1.0)
    try:
        return clamp_zoom(float(zoom_raw))
    except (TypeError, ValueError):
        return 1.0


def save_dashboard_config(
    config_path: str,
    thresholds: Dict[str, GaugeThreshold],
    unit_preferences: Optional[UnitPreferences] = None,
    zoom: float = 1.0,
) -> None:
    path = Path(config_path)
    units = unit_preferences or DEFAULT_UNIT_PREFERENCES
    existing_data: Dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing_data = loaded
        except Exception:
            existing_data = {}

    data = {
        "gauges": {},
        "units": {
            "speed": units.speed,
            "temperature": units.temperature,
        },
        "display": {
            "zoom": round(clamp_zoom(zoom), 2),
        },
    }
    for key in ("pid_overrides", "custom_gauges"):
        value = existing_data.get(key)
        if isinstance(value, dict):
            data[key] = value
    for key in sorted(thresholds):
        threshold = thresholds[key]
        data["gauges"][key] = {
            "warning": threshold.warning,
            "critical": threshold.critical,
            "direction": threshold.direction,
        }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
