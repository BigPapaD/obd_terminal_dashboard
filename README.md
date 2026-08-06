# OBD-II Terminal Dashboard

A small Python terminal dashboard that talks to a USB ELM327 adapter over serial and renders live OBD-II gauges for values such as RPM, speed, engine load, coolant temperature, and fuel level.

## Features

- Connects to an ELM327 adapter over serial
- Displays a simple interactive terminal dashboard with regular bars
- Shows speed as a large high-visibility digital readout panel
- Supports a demo mode with simulated values
- Lets you choose which gauges to display with `--gauge`
- Supports per-gauge warning and critical thresholds from a config file
- Lets you tune warn/crit settings live with arrow keys and save without leaving the app

## Project structure

- `app.py`: Small entrypoint and CLI wiring
- `models.py`: Shared dataclasses and constants
- `obd_core.py`: Serial/ELM327 communication, PID parsing, gauge definitions
- `config_io.py`: Config load/save for thresholds and units
- `display_logic.py`: Shared formatting and threshold/unit logic
- `interactive_ui.py`: Curses interactive dashboard
- `plain_dashboard.py`: Plain terminal rendering loop

## Installation

On Linux:

```bash
cd ~/obd_terminal_dashboard
python3 -m pip install -r requirements.txt
```

## Usage

Run with a demo mode:

```bash
python3 app.py --demo
```

Use plain non-interactive output mode:

```bash
python3 app.py --demo --plain
```

Run against a real adapter (example `/dev/ttyUSB0`):

```bash
python3 app.py --port /dev/ttyUSB0
```

Choose a subset of gauges:

```bash
python3 app.py --port /dev/ttyUSB0 --gauge rpm --gauge speed --gauge fuel_level
```

Disable color output:

```bash
python3 app.py --demo --no-color
```

## Configuring thresholds

The app reads `dashboard_config.json` by default. You can change warning and critical values per gauge.

Each gauge also supports `direction`:

- `high`: warn/crit trigger when value rises (good for RPM, coolant temp, throttle)
- `low`: warn/crit trigger when value drops (good for fuel level)

RPM example:

```json
{
	"gauges": {
		"rpm": {
			"warning": 4200,
			"critical": 5200,
			"direction": "high"
		}
	}
}
```

Fuel example (reversed thresholds from minimum side):

```json
{
	"gauges": {
		"fuel_level": {
			"warning": 20,
			"critical": 10,
			"direction": "low"
		}
	}
}
```

Use a custom config path:

```bash
python3 app.py --demo --config ./dashboard_config.json
```

### Display zoom

You can scale the dashboard with a global zoom value:

```json
{
	"display": {
		"zoom": 1.2
	}
}
```

Higher `zoom` means larger text/spacing and narrower bars so everything still fits the screen.
Recommended range is `0.7` to `3.0`.

### Configuring PIDs and custom gauges

You can override built-in PIDs without editing Python code:

```json
{
	"pid_overrides": {
		"rpm": "0C",
		"speed": "0D"
	}
}
```

You can also define custom gauges:

```json
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
```

Supported parser names for `custom_gauges` are:

- `rpm`
- `speed`
- `engine_load`
- `coolant_temp`
- `fuel_level`
- `intake_temp`
- `throttle`

## Interactive controls

- `Up` / `Down`: select gauge row
- `Tab`: switch editing between `warning` and `critical`
- `Left` / `Right`: decrease/increase selected value
- `Left click`: focus panel and select gauge/speed target for editing
- `Right click`: toggle active field between `warning` and `critical`
- `Mouse wheel`: tune the active threshold while in edit mode
- `d`: toggle threshold direction (`high` or `low`)
- `+` / `-`: decrease/increase refresh interval
- `z` / `x`: zoom in/out (interactive mode)
- `s`: save current thresholds to your config file
- `q`: quit

## Notes

- The ELM327 adapter must be plugged in and visible as a serial device such as `/dev/ttyUSB0`, `/dev/ttyACM0`, or `/dev/rfcomm0`.
- If you get a permission denied error, add your user to the `dialout` group and relogin:

```bash
sudo usermod -aG dialout "$USER"
```
- Some vehicles need a few seconds before responding to OBD-II queries.
- If your adapter is not detected automatically, try passing the serial port explicitly with `--port`.
