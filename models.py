from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class GaugeSpec:
    key: str
    label: str
    pid: str
    min_value: float
    max_value: float
    unit: str
    formatter: str
    parser: Callable[[bytes], float]


@dataclass
class GaugeThreshold:
    warning: Optional[float] = None
    critical: Optional[float] = None
    direction: str = "high"


@dataclass(frozen=True)
class PanelRect:
    top: int
    left: int
    height: int
    width: int


@dataclass
class UnitPreferences:
    speed: str = "kmh"
    temperature: str = "c"


DEFAULT_THRESHOLDS: Dict[str, GaugeThreshold] = {
    "rpm": GaugeThreshold(warning=4200, critical=5200, direction="high"),
    "speed": GaugeThreshold(warning=130, critical=170, direction="high"),
    "engine_load": GaugeThreshold(warning=75, critical=90, direction="high"),
    "coolant_temp": GaugeThreshold(warning=102, critical=112, direction="high"),
    "fuel_level": GaugeThreshold(warning=20, critical=10, direction="low"),
    "intake_temp": GaugeThreshold(warning=50, critical=65, direction="high"),
    "throttle": GaugeThreshold(warning=70, critical=90, direction="high"),
}


DEFAULT_UNIT_PREFERENCES = UnitPreferences(speed="kmh", temperature="c")
SPEED_KMH_TO_MPH = 0.621371
TEMP_GAUGE_KEYS = {"coolant_temp", "intake_temp"}


ANSI_COLORS: Dict[str, str] = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "bright_cyan": "\033[96m",
    "bright_magenta": "\033[95m",
    "bright_blue": "\033[94m",
    "dim_red": "\033[2;31m",
    "dim_yellow": "\033[2;33m",
    "dim_blue": "\033[2;34m",
}
