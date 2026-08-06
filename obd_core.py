from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence
import math
import time

import serial
import serial.tools.list_ports

from models import GaugeSpec


class OBDClient:
    def __init__(self, port: Optional[str] = None, baudrate: int = 115200) -> None:
        self.port = port
        self.baudrate = baudrate
        self.serial = None

    @staticmethod
    def _sorted_ports(devices: Sequence[str]) -> List[str]:
        # Prefer common Linux serial adapter device names first.
        linux_priority = ("/dev/ttyUSB", "/dev/ttyACM", "/dev/rfcomm")

        def rank(device: str) -> tuple[int, str]:
            for idx, prefix in enumerate(linux_priority):
                if device.startswith(prefix):
                    return (idx, device)
            return (len(linux_priority), device)

        return sorted(devices, key=rank)

    def connect(self) -> str:
        discovered_ports = [port.device for port in serial.tools.list_ports.comports()]
        ports = [self.port] if self.port else self._sorted_ports(discovered_ports)
        if not ports:
            raise RuntimeError("No serial ports were found. Plug in the ELM327 adapter or use --demo.")

        last_error: Optional[Exception] = None
        for port_name in ports:
            try:
                self.serial = serial.Serial(port_name, self.baudrate, timeout=1)
                time.sleep(0.5)
                self._send_command("ATZ")
                self._send_command("ATE0")
                self._send_command("ATL0")
                self._send_command("ATS0")
                self._send_command("ATSP0")
                return port_name
            except Exception as exc:  # pragma: no cover - depends on hardware
                last_error = exc
                if self.serial is not None:
                    self.serial.close()
                    self.serial = None

        guidance = ""
        if last_error and "Permission denied" in str(last_error):
            guidance = " (Linux hint: add your user to the dialout group, then relogin.)"
        raise RuntimeError(f"Unable to connect to ELM327 adapter: {last_error}{guidance}")

    def disconnect(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def _send_command(self, command: str) -> str:
        if self.serial is None:
            raise RuntimeError("Serial connection is not open")
        self.serial.reset_input_buffer()
        self.serial.write((command + "\r").encode("ascii"))
        self.serial.flush()
        time.sleep(0.2)

        response = []
        while True:
            line = self.serial.readline()
            if not line:
                break
            response.append(line.decode("ascii", errors="ignore"))
            if line.endswith(b">") or line.endswith(b"\r"):
                break
        return "".join(response).strip()

    def read_gauge(self, gauge: GaugeSpec) -> Optional[float]:
        response = self._send_command(f"01{gauge.pid}")
        return parse_obd_response(response, gauge.pid, gauge.parser)


def parse_obd_response(response: str, pid: str, parser) -> Optional[float]:
    cleaned = response.strip().replace("\r", " ").replace("\n", " ").upper()
    if not cleaned or "NO DATA" in cleaned or "CAN ERROR" in cleaned:
        return None

    # ELM327 adapters often prepend text (for example "SEARCHING...") or
    # include prompt characters; keep only hexadecimal byte tokens.
    tokens = [
        part
        for part in cleaned.replace(">", " ").split()
        if part and len(part) == 2 and all(ch in "0123456789ABCDEF" for ch in part)
    ]
    if len(tokens) < 3:
        return None

    pid_byte = f"{int(pid, 16):02X}"
    for idx in range(len(tokens) - 2):
        if tokens[idx] == "41" and tokens[idx + 1] == pid_byte:
            payload_hex = "".join(tokens[idx:])
            try:
                payload = bytes.fromhex(payload_hex)
            except ValueError:
                return None
            if len(payload) < 3:
                return None
            return parser(payload[2:])
    return None


def rpm_parser(payload: bytes) -> float:
    if len(payload) < 2:
        raise ValueError("RPM response is too short")
    return ((payload[0] << 8) | payload[1]) / 4.0


def speed_parser(payload: bytes) -> float:
    if not payload:
        raise ValueError("Speed response is empty")
    return float(payload[0])


def engine_load_parser(payload: bytes) -> float:
    if not payload:
        raise ValueError("Engine load response is empty")
    return round((payload[0] * 100.0) / 255.0, 1)


def coolant_temp_parser(payload: bytes) -> float:
    if not payload:
        raise ValueError("Coolant temp response is empty")
    return float(payload[0] - 40)


def fuel_level_parser(payload: bytes) -> float:
    if not payload:
        raise ValueError("Fuel level response is empty")
    return round((payload[0] * 100.0) / 255.0, 1)


def intake_temp_parser(payload: bytes) -> float:
    if not payload:
        raise ValueError("Intake temp response is empty")
    return float(payload[0] - 40)


def throttle_pos_parser(payload: bytes) -> float:
    if not payload:
        raise ValueError("Throttle position response is empty")
    return (payload[0] * 100.0) / 255.0


PARSER_REGISTRY: Dict[str, Callable[[bytes], float]] = {
    "rpm": rpm_parser,
    "speed": speed_parser,
    "engine_load": engine_load_parser,
    "coolant_temp": coolant_temp_parser,
    "fuel_level": fuel_level_parser,
    "intake_temp": intake_temp_parser,
    "throttle": throttle_pos_parser,
}


DEFAULT_GAUGE_SPECS: Dict[str, GaugeSpec] = {
    "rpm": GaugeSpec("rpm", "RPM", "0C", 0, 8000, "rpm", "{:.0f}", rpm_parser),
    "speed": GaugeSpec("speed", "Speed", "0D", 0, 220, "km/h", "{:.0f}", speed_parser),
    "engine_load": GaugeSpec("engine_load", "Engine Load", "04", 0, 100, "%", "{:.1f}", engine_load_parser),
    "coolant_temp": GaugeSpec("coolant_temp", "Coolant", "05", -40, 130, "°C", "{:.0f}", coolant_temp_parser),
    "fuel_level": GaugeSpec("fuel_level", "Fuel", "2F", 0, 100, "%", "{:.1f}", fuel_level_parser),
    "intake_temp": GaugeSpec("intake_temp", "Intake", "0F", -40, 130, "°C", "{:.0f}", intake_temp_parser),
    "throttle": GaugeSpec("throttle", "Throttle", "11", 0, 100, "%", "{:.1f}", throttle_pos_parser),
}


GAUGE_SPECS: Dict[str, GaugeSpec] = dict(DEFAULT_GAUGE_SPECS)


def _validate_pid(pid: str, key: str) -> str:
    normalized = pid.strip().upper()
    if len(normalized) != 2 or any(ch not in "0123456789ABCDEF" for ch in normalized):
        raise RuntimeError(f"Invalid PID '{pid}' for gauge '{key}'. Expected a 2-digit hex byte, for example '0C'.")
    return normalized


def reset_gauge_specs() -> None:
    GAUGE_SPECS.clear()
    GAUGE_SPECS.update(DEFAULT_GAUGE_SPECS)


def apply_gauge_config(config_path: str) -> None:
    reset_gauge_specs()
    path = Path(config_path)
    if not path.exists():
        return

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Unable to read config file '{config_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("Config root must be a JSON object")

    pid_overrides = data.get("pid_overrides", {})
    if pid_overrides is not None:
        if not isinstance(pid_overrides, dict):
            raise RuntimeError("Config key 'pid_overrides' must be a JSON object")
        for key, pid_raw in pid_overrides.items():
            if key not in GAUGE_SPECS:
                continue
            if not isinstance(pid_raw, str):
                raise RuntimeError(f"PID override for gauge '{key}' must be a string")
            pid = _validate_pid(pid_raw, key)
            GAUGE_SPECS[key] = replace(GAUGE_SPECS[key], pid=pid)

    custom_gauges = data.get("custom_gauges", {})
    if custom_gauges is not None:
        if not isinstance(custom_gauges, dict):
            raise RuntimeError("Config key 'custom_gauges' must be a JSON object")
        for key, settings in custom_gauges.items():
            if not isinstance(settings, dict):
                continue

            pid_raw = settings.get("pid")
            parser_name_raw = settings.get("parser")
            if not isinstance(pid_raw, str) or not isinstance(parser_name_raw, str):
                raise RuntimeError(
                    f"Custom gauge '{key}' must define string fields 'pid' and 'parser'."
                )

            parser_name = parser_name_raw.strip().lower()
            parser_fn = PARSER_REGISTRY.get(parser_name)
            if parser_fn is None:
                available = ", ".join(sorted(PARSER_REGISTRY))
                raise RuntimeError(
                    f"Custom gauge '{key}' uses unknown parser '{parser_name_raw}'. "
                    f"Available parsers: {available}"
                )

            pid = _validate_pid(pid_raw, key)
            label = settings.get("label") if isinstance(settings.get("label"), str) else key.replace("_", " ").title()
            min_value = float(settings.get("min", 0.0))
            max_value = float(settings.get("max", 100.0))
            if max_value <= min_value:
                raise RuntimeError(f"Custom gauge '{key}' must define max greater than min")
            unit = settings.get("unit") if isinstance(settings.get("unit"), str) else ""
            formatter = settings.get("formatter") if isinstance(settings.get("formatter"), str) else "{:.1f}"

            GAUGE_SPECS[key] = GaugeSpec(
                key=key,
                label=label,
                pid=pid,
                min_value=min_value,
                max_value=max_value,
                unit=unit,
                formatter=formatter,
                parser=parser_fn,
            )


DEMO_WAVE_SPECS: Dict[str, tuple[float, float, float]] = {
    "rpm": (1200.0, 1200.0, 1.5),
    "speed": (45.0, 25.0, 2.0),
    "engine_load": (30.0, 20.0, 1.2),
    "coolant_temp": (88.0, 6.0, 3.0),
    "fuel_level": (70.0, 10.0, 4.0),
    "intake_temp": (32.0, 8.0, 2.5),
    "throttle": (15.0, 20.0, 1.0),
}


def build_gauge_list(requested: Sequence[str]) -> List[GaugeSpec]:
    if not requested:
        return [GAUGE_SPECS[name] for name in ["rpm", "speed", "engine_load", "coolant_temp", "fuel_level"]]

    gauges: List[GaugeSpec] = []
    for item in requested:
        key = item.strip().lower()
        if key not in GAUGE_SPECS:
            raise ValueError(f"Unknown gauge '{item}'. Available: {', '.join(sorted(GAUGE_SPECS))}")
        gauges.append(GAUGE_SPECS[key])
    return gauges


def collect_live_values(client: OBDClient, gauges: Sequence[GaugeSpec]) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for gauge in gauges:
        try:
            value = client.read_gauge(gauge)
        except Exception:
            value = None
        if value is not None:
            values[gauge.key] = value
    return values


def collect_demo_values() -> Dict[str, float]:
    now = time.time()
    values: Dict[str, float] = {}
    for key, (base, amplitude, period) in DEMO_WAVE_SPECS.items():
        values[key] = base + amplitude * math.sin(now / period)
    return values


def merge_latest_values(previous: Dict[str, float], incoming: Dict[str, float]) -> Dict[str, float]:
    merged = dict(previous)
    merged.update(incoming)
    return merged
