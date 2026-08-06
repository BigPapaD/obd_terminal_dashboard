import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import GaugeSpec, GaugeThreshold, adjust_threshold, coolant_temp_parser, engine_load_parser, fuel_level_parser, load_dashboard_config, parse_obd_response, render_bar, rpm_parser, speed_parser
from obd_core import GAUGE_SPECS, apply_gauge_config, build_gauge_list, reset_gauge_specs


def test_rpm_parser() -> None:
    response = "41 0C 1A F8"
    value = parse_obd_response(response, "0C", rpm_parser)
    assert value == 1726.0


def test_speed_parser() -> None:
    response = "41 0D 50"
    value = parse_obd_response(response, "0D", speed_parser)
    assert value == 80.0


def test_engine_load_parser() -> None:
    response = "41 04 80"
    value = parse_obd_response(response, "04", engine_load_parser)
    assert value == 50.2


def test_coolant_temp_parser() -> None:
    response = "41 05 5A"
    value = parse_obd_response(response, "05", coolant_temp_parser)
    assert value == 50.0


def test_fuel_level_parser() -> None:
    response = "41 2F 80"
    value = parse_obd_response(response, "2F", fuel_level_parser)
    assert value == 50.2


def test_render_bar_shows_critical_color_when_value_is_high() -> None:
    line = render_bar(
        label="RPM",
        value=5300.0,
        minimum=0.0,
        maximum=8000.0,
        unit="rpm",
        threshold=GaugeThreshold(warning=4200, critical=5200),
        use_color=True,
    )
    assert "\033[31m" in line


def test_render_bar_shows_critical_color_when_value_is_low() -> None:
    line = render_bar(
        label="Fuel",
        value=7.0,
        minimum=0.0,
        maximum=100.0,
        unit="%",
        threshold=GaugeThreshold(warning=20, critical=10, direction="low"),
        use_color=True,
    )
    assert "\033[31m" in line


def test_load_dashboard_config_applies_override(tmp_path: Path) -> None:
    config_path = tmp_path / "dashboard_config.json"
    config_path.write_text(
        json.dumps(
            {
                "gauges": {
                    "rpm": {
                        "warning": 4100,
                        "critical": 5100,
                        "direction": "high",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    thresholds = load_dashboard_config(str(config_path))
    assert thresholds["rpm"] == GaugeThreshold(warning=4100.0, critical=5100.0, direction="high")


def test_load_dashboard_config_accepts_low_direction(tmp_path: Path) -> None:
    config_path = tmp_path / "dashboard_config.json"
    config_path.write_text(
        json.dumps(
            {
                "gauges": {
                    "fuel_level": {
                        "warning": 25,
                        "critical": 12,
                        "direction": "low",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    thresholds = load_dashboard_config(str(config_path))
    assert thresholds["fuel_level"] == GaugeThreshold(warning=25.0, critical=12.0, direction="low")


def test_adjust_threshold_keeps_high_direction_order() -> None:
    gauge = GaugeSpec("rpm", "RPM", "0C", 0, 8000, "rpm", "{:.0f}", rpm_parser)
    threshold = GaugeThreshold(warning=4200, critical=5200, direction="high")
    updated = adjust_threshold(threshold, gauge, "warning", 1500)
    assert updated.warning == 5700
    assert updated.critical == 5700


def test_adjust_threshold_keeps_low_direction_order() -> None:
    gauge = GaugeSpec("fuel_level", "Fuel", "2F", 0, 100, "%", "{:.1f}", fuel_level_parser)
    threshold = GaugeThreshold(warning=20, critical=10, direction="low")
    updated = adjust_threshold(threshold, gauge, "critical", 15)
    assert updated.warning == 25
    assert updated.critical == 25


def test_apply_gauge_config_overrides_pid(tmp_path: Path) -> None:
    config_path = tmp_path / "dashboard_config.json"
    config_path.write_text(
        json.dumps(
            {
                "pid_overrides": {
                    "rpm": "0E",
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        apply_gauge_config(str(config_path))
        assert GAUGE_SPECS["rpm"].pid == "0E"
    finally:
        reset_gauge_specs()


def test_apply_gauge_config_adds_custom_gauge_and_thresholds(tmp_path: Path) -> None:
    config_path = tmp_path / "dashboard_config.json"
    config_path.write_text(
        json.dumps(
            {
                "custom_gauges": {
                    "boost": {
                        "label": "Boost",
                        "pid": "0B",
                        "parser": "speed",
                        "min": 0,
                        "max": 255,
                        "unit": "kPa",
                        "formatter": "{:.0f}"
                    }
                },
                "gauges": {
                    "boost": {
                        "warning": 190,
                        "critical": 220,
                        "direction": "high"
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        apply_gauge_config(str(config_path))
        gauges = build_gauge_list(["boost"])
        assert gauges[0].key == "boost"
        assert gauges[0].pid == "0B"

        thresholds = load_dashboard_config(str(config_path))
        assert thresholds["boost"] == GaugeThreshold(warning=190.0, critical=220.0, direction="high")
    finally:
        reset_gauge_specs()
