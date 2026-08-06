from __future__ import annotations

import argparse
import sys

from config_io import load_dashboard_config, load_display_zoom, load_unit_preferences
from display_logic import adjust_threshold
from interactive_ui import run_interactive
from models import GaugeSpec, GaugeThreshold
from obd_core import (
    OBDClient,
    apply_gauge_config,
    build_gauge_list,
    coolant_temp_parser,
    engine_load_parser,
    fuel_level_parser,
    intake_temp_parser,
    parse_obd_response,
    rpm_parser,
    speed_parser,
    throttle_pos_parser,
)
from plain_dashboard import render_bar, run_demo, run_live


__all__ = [
    "GaugeSpec",
    "GaugeThreshold",
    "OBDClient",
    "apply_gauge_config",
    "adjust_threshold",
    "build_gauge_list",
    "coolant_temp_parser",
    "engine_load_parser",
    "fuel_level_parser",
    "intake_temp_parser",
    "load_dashboard_config",
    "load_display_zoom",
    "load_unit_preferences",
    "parse_obd_response",
    "render_bar",
    "rpm_parser",
    "run_demo",
    "run_interactive",
    "run_live",
    "speed_parser",
    "throttle_pos_parser",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal OBD-II dashboard for ELM327 adapters")
    parser.add_argument("--port", help="serial device path, for example /dev/ttyUSB0, /dev/ttyACM0, or /dev/rfcomm0")
    parser.add_argument("--baudrate", type=int, default=115200, help="serial baud rate")
    parser.add_argument("--demo", action="store_true", help="run with simulated values")
    parser.add_argument("--gauge", action="append", default=[], help="gauge to display (rpm, speed, engine_load, coolant_temp, fuel_level, intake_temp, throttle)")
    parser.add_argument("--interval", type=float, default=0.25, help="refresh interval in seconds")
    parser.add_argument("--config", default="dashboard_config.json", help="path to dashboard config JSON")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI color output")
    parser.add_argument("--plain", action="store_true", help="use plain non-interactive output mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        apply_gauge_config(args.config)
        gauges = build_gauge_list(args.gauge)
        thresholds = load_dashboard_config(args.config)
        unit_preferences = load_unit_preferences(args.config)
        zoom = load_display_zoom(args.config)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        sys.exit(2)
    except RuntimeError as exc:
        sys.stderr.write(str(exc) + "\n")
        sys.exit(2)

    use_color = (not args.no_color) and sys.stdout.isatty()

    if args.demo:
        if args.plain:
            run_demo(gauges, thresholds, unit_preferences, args.interval, use_color=use_color, zoom=zoom)
        else:
            run_interactive(
                gauges=gauges,
                thresholds=thresholds,
                unit_preferences=unit_preferences,
                interval=args.interval,
                config_path=args.config,
                demo=True,
                client=None,
                zoom=zoom,
            )
        return

    client = OBDClient(port=args.port, baudrate=args.baudrate)
    try:
        port_name = client.connect()
        print(f"Connected to {port_name}")
        if args.plain:
            run_live(client, gauges, thresholds, unit_preferences, args.interval, use_color=use_color, zoom=zoom)
        else:
            run_interactive(
                gauges=gauges,
                thresholds=thresholds,
                unit_preferences=unit_preferences,
                interval=args.interval,
                config_path=args.config,
                demo=False,
                client=client,
                zoom=zoom,
            )
    except KeyboardInterrupt:
        print("\nStopped")
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
