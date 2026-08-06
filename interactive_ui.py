from __future__ import annotations

from dataclasses import replace
import time
from typing import Dict, List, Sequence

from config_io import save_dashboard_config
from display_logic import (
    adjust_threshold,
    clamp,
    display_unit_for_gauge,
    format_gauge_offset,
    format_gauge_value,
    render_regular_bar,
    segment_level,
    threshold_status,
    threshold_step_base,
    toggle_unit_preferences,
    value_to_display,
)
from models import GaugeSpec, GaugeThreshold, PanelRect, UnitPreferences
from obd_core import GAUGE_SPECS, OBDClient, collect_demo_values, collect_live_values, merge_latest_values


BIG_SPEED_GLYPHS: Dict[str, tuple[str, str, str, str, str]] = {
    "0": (" ### ", "#   #", "#   #", "#   #", " ### "),
    "1": ("  #  ", " ##  ", "  #  ", "  #  ", " ### "),
    "2": (" ### ", "    #", " ### ", "#    ", "#####"),
    "3": ("#### ", "    #", " ### ", "    #", "#### "),
    "4": ("#   #", "#   #", "#####", "    #", "    #"),
    "5": ("#####", "#    ", "#### ", "    #", "#### "),
    "6": (" ### ", "#    ", "#### ", "#   #", " ### "),
    "7": ("#####", "   # ", "  #  ", " #   ", "#    "),
    "8": (" ### ", "#   #", " ### ", "#   #", " ### "),
    "9": (" ### ", "#   #", " ####", "    #", " ### "),
    "-": ("     ", "     ", "#####", "     ", "     "),
    " ": ("     ", "     ", "     ", "     ", "     "),
}


def render_big_speed_lines(speed_digits: str, x_scale: int, y_scale: int) -> List[str]:
    rows = ["", "", "", "", ""]
    for char in speed_digits:
        glyph = BIG_SPEED_GLYPHS.get(char, BIG_SPEED_GLYPHS[" "])
        for idx in range(5):
            expanded = "".join(ch * x_scale for ch in glyph[idx])
            rows[idx] += expanded + (" " * x_scale)

    output: List[str] = []
    for row in rows:
        line = row.rstrip()
        for _ in range(y_scale):
            output.append(line)
    return output


def point_in_rect(y: int, x: int, rect: PanelRect) -> bool:
    return rect.top <= y < (rect.top + rect.height) and rect.left <= x < (rect.left + rect.width)


def gauge_index_from_mouse(y: int, rect: PanelRect, gauge_count: int) -> int | None:
    row = y - (rect.top + 1)
    visible_rows = max(0, min(gauge_count, rect.height - 2))
    if 0 <= row < visible_rows:
        return row
    return None


def safe_addstr(stdscr, y: int, x: int, text: str, attr: int = 0) -> None:
    max_y, max_x = stdscr.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    if not text:
        return
    clipped = text[: max(0, max_x - x)]
    if not clipped:
        return
    try:
        if attr:
            stdscr.addstr(y, x, clipped, attr)
        else:
            stdscr.addstr(y, x, clipped)
    except Exception:
        return


def draw_panel(
    stdscr,
    rect: PanelRect,
    title: str = "",
    border_attr: int = 0,
    title_attr: int = 0,
) -> None:
    top = rect.top
    left = rect.left
    height = rect.height
    width = rect.width
    if height < 3 or width < 4:
        return
    right = left + width - 1
    bottom = top + height - 1
    horiz = "─" * (width - 2)
    safe_addstr(stdscr, top, left, f"┌{horiz}┐", border_attr)
    for row in range(top + 1, bottom):
        safe_addstr(stdscr, row, left, "│", border_attr)
        safe_addstr(stdscr, row, right, "│", border_attr)
    safe_addstr(stdscr, bottom, left, f"└{horiz}┘", border_attr)

    if title and width > 8:
        title_text = f" {title.upper()} "
        safe_addstr(stdscr, top, left + 2, title_text[: width - 4], title_attr or border_attr)


def proportional_sizes(total: int, ratios: Sequence[int], minimum: int) -> List[int]:
    if not ratios:
        return [total]
    ratio_sum = sum(ratios)
    if ratio_sum <= 0:
        return [total]

    sizes = [max(minimum, (total * ratio) // ratio_sum) for ratio in ratios]
    current = sum(sizes)

    while current > total:
        idx = max(range(len(sizes)), key=lambda i: sizes[i])
        if sizes[idx] <= minimum:
            break
        sizes[idx] -= 1
        current -= 1

    idx = 0
    while current < total:
        sizes[idx % len(sizes)] += 1
        current += 1
        idx += 1
    return sizes


def build_layout(max_y: int, max_x: int, edit_mode: bool = True) -> Dict[str, PanelRect]:
    footer_height = 1
    body_top = 1
    body_height = max_y - body_top - footer_height
    right_width = max(28, min(38, max_x // 3))
    left_width = max_x - right_width

    main_rect = PanelRect(top=body_top, left=0, height=body_height, width=left_width)
    if edit_mode:
        right_heights = proportional_sizes(body_height, [34, 30, 36], minimum=5)
        speed_rect = PanelRect(top=body_top, left=left_width, height=right_heights[0], width=right_width)
        alerts_rect = PanelRect(
            top=body_top + right_heights[0],
            left=left_width,
            height=right_heights[1],
            width=right_width,
        )
        controls_rect = PanelRect(
            top=alerts_rect.top + alerts_rect.height,
            left=left_width,
            height=right_heights[2],
            width=right_width,
        )
    else:
        right_heights = proportional_sizes(body_height, [62, 38], minimum=6)
        speed_rect = PanelRect(top=body_top, left=left_width, height=right_heights[0], width=right_width)
        alerts_rect = PanelRect(
            top=body_top + right_heights[0],
            left=left_width,
            height=right_heights[1],
            width=right_width,
        )
        controls_rect = PanelRect(
            top=alerts_rect.top + alerts_rect.height,
            left=left_width,
            height=0,
            width=right_width,
        )
    return {
        "main": main_rect,
        "speed": speed_rect,
        "alerts": alerts_rect,
        "controls": controls_rect,
        "footer": PanelRect(top=max_y - 1, left=0, height=1, width=max_x),
    }


def init_curses_theme(curses_module) -> Dict[str, int]:
    theme = {
        "header": 0,
        "border": 0,
        "title": 0,
        "title_focus": 0,
        "selected": 0,
        "ok": 0,
        "warn": 0,
        "crit": 0,
        "muted": 0,
        "footer": 0,
        "row_emphasis": 0,
    }
    if not curses_module.has_colors():
        return theme

    curses_module.start_color()
    if hasattr(curses_module, "use_default_colors"):
        curses_module.use_default_colors()

    curses_module.init_pair(1, curses_module.COLOR_CYAN, -1)
    curses_module.init_pair(2, curses_module.COLOR_BLUE, -1)
    curses_module.init_pair(3, curses_module.COLOR_MAGENTA, -1)
    curses_module.init_pair(4, curses_module.COLOR_GREEN, -1)
    curses_module.init_pair(5, curses_module.COLOR_YELLOW, -1)
    curses_module.init_pair(6, curses_module.COLOR_RED, -1)
    curses_module.init_pair(7, curses_module.COLOR_WHITE, -1)

    theme["header"] = curses_module.color_pair(1) | curses_module.A_BOLD
    theme["border"] = curses_module.color_pair(2)
    theme["title"] = curses_module.color_pair(3) | curses_module.A_BOLD
    theme["title_focus"] = curses_module.color_pair(1) | curses_module.A_BOLD
    theme["selected"] = curses_module.color_pair(3) | curses_module.A_BOLD
    theme["ok"] = curses_module.color_pair(4)
    theme["warn"] = curses_module.color_pair(5) | curses_module.A_BOLD
    theme["crit"] = curses_module.color_pair(6) | curses_module.A_BOLD
    theme["muted"] = curses_module.color_pair(7)
    theme["footer"] = curses_module.color_pair(1)
    theme["row_emphasis"] = curses_module.A_BOLD
    return theme


def render_status_row(
    gauges: Sequence[GaugeSpec],
    values: Dict[str, float],
    thresholds: Dict[str, GaugeThreshold],
    interval: float,
    message: str,
) -> str:
    crit_count = 0
    warn_count = 0
    for gauge in gauges:
        value = values.get(gauge.key)
        if value is None:
            continue
        level = segment_level(value, thresholds.get(gauge.key, GaugeThreshold()))
        if level == "critical":
            crit_count += 1
        elif level == "warning":
            warn_count += 1

    status = f"CRIT:{crit_count} WARN:{warn_count}"
    return f"OBD-II LINK // CYBERJEEP  |  refresh:{interval:.2f}s  |  {status}  |  {message}"


def render_alert_lines(
    gauges: Sequence[GaugeSpec],
    values: Dict[str, float],
    thresholds: Dict[str, GaugeThreshold],
    unit_preferences: UnitPreferences,
    limit: int,
) -> List[str]:
    critical: List[str] = []
    warning: List[str] = []

    for gauge in gauges:
        value = values.get(gauge.key)
        if value is None:
            continue
        threshold = thresholds.get(gauge.key, GaugeThreshold())
        level = segment_level(value, threshold)
        if level == "critical":
            critical.append(f"CRIT {gauge.label:<11} {format_gauge_value(gauge, value, unit_preferences)} {display_unit_for_gauge(gauge, unit_preferences)}")
        elif level == "warning":
            warning.append(f"WARN {gauge.label:<11} {format_gauge_value(gauge, value, unit_preferences)} {display_unit_for_gauge(gauge, unit_preferences)}")

    lines = critical + warning
    if not lines:
        lines = ["All gauges nominal"]
    return lines[:limit]


def render_speed_row(speed_value: float, width: int, unit_preferences: UnitPreferences) -> str:
    gauge = GAUGE_SPECS["speed"]
    text = f"{format_gauge_value(gauge, speed_value, unit_preferences):>6} {display_unit_for_gauge(gauge, unit_preferences)}"
    if width <= len(text):
        return text[:width]
    pad_left = (width - len(text)) // 2
    return (" " * pad_left + text).ljust(width)


def render_widget_bar(value: float, minimum: float, maximum: float, width: int) -> str:
    if width <= 0:
        return ""
    ratio = clamp((value - minimum) / (maximum - minimum), 0.0, 1.0) if maximum > minimum else 0.0
    return render_regular_bar(ratio, width)


def row_attr_from_state(state: str, selected: bool, theme: Dict[str, int]) -> int:
    if state == "CRIT":
        base = theme["crit"]
    elif state == "WARN":
        base = theme["warn"]
    else:
        base = theme["ok"]
    if selected:
        return base | theme["selected"] | theme.get("row_emphasis", 0)
    return base | theme.get("row_emphasis", 0)


def draw_gauges_widget(
    stdscr,
    rect: PanelRect,
    gauges: Sequence[GaugeSpec],
    values: Dict[str, float],
    thresholds: Dict[str, GaugeThreshold],
    selected_index: int,
    selected_field: str,
    edit_mode: bool,
    edit_target: str,
    unit_preferences: UnitPreferences,
    zoom: float,
    theme: Dict[str, int],
) -> None:
    row_start = rect.top + 1
    row_end = rect.top + rect.height - 1
    row_width = max(1, rect.width - 3)
    show_selected = edit_mode and edit_target == "selected"
    for idx, gauge in enumerate(gauges):
        target_row = row_start + idx
        if target_row >= row_end:
            break
        value = values.get(gauge.key, 0.0)
        threshold = thresholds.get(gauge.key, GaugeThreshold())
        state = threshold_status(value, threshold)
        row = render_compact_row(
            gauge,
            value,
            threshold,
            selected=(idx == selected_index),
            edit_mode=edit_mode,
            edit_target=edit_target,
            unit_preferences=unit_preferences,
            zoom=zoom,
            row_width=row_width,
        )
        safe_addstr(
            stdscr,
            target_row,
            rect.left + 1,
            row[:row_width],
            row_attr_from_state(state, show_selected and idx == selected_index, theme),
        )


def draw_speed_widget(
    stdscr,
    rect: PanelRect,
    values: Dict[str, float],
    thresholds: Dict[str, GaugeThreshold],
    selected_field: str,
    edit_mode: bool,
    edit_active: bool,
    edit_target: str,
    unit_preferences: UnitPreferences,
    zoom: float,
    theme: Dict[str, int],
) -> None:
    speed_gauge = GAUGE_SPECS["speed"]
    speed_threshold = thresholds.get("speed", GaugeThreshold())
    speed_value = values.get("speed", 0.0)
    inner_width = max(1, rect.width - 4)
    speed_digits = format_gauge_value(speed_gauge, speed_value, unit_preferences).rjust(3)[-3:]
    warn_text = format_gauge_value(speed_gauge, speed_threshold.warning or 0.0, unit_preferences)
    crit_text = format_gauge_value(speed_gauge, speed_threshold.critical or 0.0, unit_preferences)
    unit_text = display_unit_for_gauge(speed_gauge, unit_preferences)
    edit_tag = "SPEED EDIT" if edit_mode and edit_target == "speed" and edit_active else "SPEED READY"
    speed_focus_attr = theme["selected"] if edit_mode and edit_target == "speed" else theme["title_focus"]

    reserved_rows = 2 if edit_mode and rect.height >= 7 else 0
    unit_rows = 0
    digit_rows_available = max(1, rect.height - 2 - reserved_rows - unit_rows)

    # Higher zoom prefers a larger glyph scale; renderer still caps to fit available panel space.
    zoom_pref = max(0.7, min(3.0, zoom))
    if zoom_pref >= 1.8:
        scale_candidates = [(3, 2), (2, 2), (2, 1), (1, 1)]
    elif zoom_pref >= 1.2:
        scale_candidates = [(2, 2), (2, 1), (1, 1)]
    else:
        scale_candidates = [(2, 1), (1, 1)]

    digit_lines = [speed_digits]
    for x_scale, y_scale in scale_candidates:
        candidate = render_big_speed_lines(speed_digits, x_scale=x_scale, y_scale=y_scale)
        if candidate and len(candidate) <= digit_rows_available and len(candidate[0]) <= inner_width:
            digit_lines = candidate
            break

    top_offset = max(0, (digit_rows_available - len(digit_lines)) // 2)
    for idx, line in enumerate(digit_lines[:digit_rows_available]):
        x_offset = max(0, (inner_width - len(line)) // 2)
        safe_addstr(stdscr, rect.top + 1 + top_offset + idx, rect.left + 2 + x_offset, line[:inner_width], speed_focus_attr)

    if edit_mode and rect.height >= 6:
        warn_row = rect.top + rect.height - 3
        safe_addstr(
            stdscr,
            warn_row,
            rect.left + 2,
            f"warn:{warn_text} crit:{crit_text} {unit_text}"[:inner_width],
            theme["warn" if selected_field == "warning" else "crit"],
        )
    if edit_mode and rect.height >= 7:
        edit_row = rect.top + rect.height - 2
        safe_addstr(stdscr, edit_row, rect.left + 2, edit_tag[:inner_width], theme["muted"])


def draw_alerts_widget(
    stdscr,
    rect: PanelRect,
    gauges: Sequence[GaugeSpec],
    values: Dict[str, float],
    thresholds: Dict[str, GaugeThreshold],
    selected_index: int,
    selected_field: str,
    edit_mode: bool,
    edit_active: bool,
    edit_target: str,
    unit_preferences: UnitPreferences,
    theme: Dict[str, int],
) -> None:
    if edit_mode:
        gauge = GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]
        threshold = thresholds.get(gauge.key, GaugeThreshold())
        value = values.get(gauge.key, 0.0)
        warning_value = threshold.warning if threshold.warning is not None else gauge.min_value
        critical_value = threshold.critical if threshold.critical is not None else gauge.max_value
        warn_offset = warning_value - value
        crit_offset = critical_value - value
        unit_text = display_unit_for_gauge(gauge, unit_preferences)
        mode_text = "EDIT" if edit_active else "READY"
        active_field = "CRITICAL" if selected_field == "critical" else "WARNING"
        compact_lines = [
            f"{gauge.label} {mode_text} {active_field}",
            f"WΔ:{format_gauge_offset(gauge, warn_offset, unit_preferences)} CΔ:{format_gauge_offset(gauge, crit_offset, unit_preferences)} {unit_text}",
            f"W:{format_gauge_value(gauge, warning_value, unit_preferences)} C:{format_gauge_value(gauge, critical_value, unit_preferences)} dir:{threshold.direction}",
        ]
        full_lines = [
            f"target: {gauge.label}",
            f"mode: {mode_text}",
            f"warn : {format_gauge_value(gauge, warning_value, unit_preferences)} ({format_gauge_offset(gauge, warn_offset, unit_preferences)}) {unit_text}",
            f"crit : {format_gauge_value(gauge, critical_value, unit_preferences)} ({format_gauge_offset(gauge, crit_offset, unit_preferences)}) {unit_text}",
            f"field: {active_field} dir:{threshold.direction}",
        ]
        max_lines = max(1, rect.height - 2)
        lines = full_lines if max_lines >= 5 else compact_lines
        for idx, line in enumerate(lines[:max_lines]):
            attr = theme["muted"]
            if line.startswith("mode:"):
                attr = theme["warn"] if edit_active else theme["ok"]
            elif line.startswith("field:") or active_field in line:
                attr = theme["crit"] if selected_field == "critical" else theme["warn"]
            safe_addstr(stdscr, rect.top + 1 + idx, rect.left + 2, line[: rect.width - 4], attr)
        return

    alert_lines = render_alert_lines(gauges, values, thresholds, unit_preferences, max(1, rect.height - 2))
    for idx, line in enumerate(alert_lines):
        attr = theme["muted"]
        if line.startswith("CRIT"):
            attr = theme["crit"]
        elif line.startswith("WARN"):
            attr = theme["warn"]
        elif line.startswith("All gauges"):
            attr = theme["ok"]
        safe_addstr(stdscr, rect.top + 1 + idx, rect.left + 2, line[: rect.width - 4], attr)


def draw_controls_widget(
    stdscr,
    rect: PanelRect,
    gauges: Sequence[GaugeSpec],
    selected_index: int,
    selected_field: str,
    edit_mode: bool,
    edit_active: bool,
    edit_target: str,
    interval: float,
    zoom: float,
    message: str,
    thresholds: Dict[str, GaugeThreshold],
    unit_preferences: UnitPreferences,
    theme: Dict[str, int],
) -> None:
    gauge = GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]
    threshold = thresholds.get(gauge.key, GaugeThreshold())
    warning_value = threshold.warning if threshold.warning is not None else gauge.min_value
    critical_value = threshold.critical if threshold.critical is not None else gauge.max_value
    warning_text = format_gauge_value(gauge, warning_value, unit_preferences)
    critical_text = format_gauge_value(gauge, critical_value, unit_preferences)
    if not edit_mode:
        mode_text = "navigate"
    elif edit_active:
        mode_text = "editing"
    else:
        mode_text = "edit-ready"
    field_text = "CRITICAL" if selected_field == "critical" else "WARNING"
    lines = [
        f"focus: {gauge.label} ({edit_target})",
        f"mode: {mode_text}",
        f"field: {field_text}",
        f"warn:{warning_text} crit:{critical_text} {display_unit_for_gauge(gauge, unit_preferences)}",
        f"dir:{threshold.direction}  refresh:{interval:.2f}s zoom:{zoom:.2f}x",
        f"{message}",
    ]
    hints = [
        "e edit mode  Enter toggle edit",
        "Tab target/field  ↑/↓ row (edit)",
        "←/→ or h/l tune  w/c field  ,/. critical",
        "u units  d direction  s save  +/- rate",
        "z/x zoom in/out",
        "Mouse: left select/focus  right field",
        "Mouse wheel: tune selected threshold",
        "q quit",
    ]

    row = rect.top + 1
    for line in lines:
        if row >= rect.top + rect.height - 1:
            break
        attr = theme["muted"]
        if line.startswith("field:"):
            attr = theme["crit"] if selected_field == "critical" else theme["warn"]
        safe_addstr(stdscr, row, rect.left + 2, line[: rect.width - 4], attr)
        row += 1

    for line in hints:
        if row >= rect.top + rect.height - 1:
            break
        safe_addstr(stdscr, row, rect.left + 2, line[: rect.width - 4], theme["header"])
        row += 1


def draw_footer(stdscr, rect: PanelRect, theme: Dict[str, int]) -> None:
    footer = "Keys: e/Tab/Enter/arrows/u/s/z/x/q | Mouse: left focus, right field, wheel tune"
    safe_addstr(stdscr, rect.top, rect.left, footer[: rect.width], theme["footer"])


def render_compact_row(
    gauge: GaugeSpec,
    value: float,
    threshold: GaugeThreshold,
    selected: bool,
    edit_mode: bool,
    edit_target: str,
    unit_preferences: UnitPreferences,
    zoom: float,
    row_width: int,
) -> str:
    state = threshold_status(value, threshold)
    is_active_target = selected and edit_target == "selected"
    pointer = "▶" if selected and edit_mode and is_active_target else " "
    safe_zoom = max(0.7, min(3.0, zoom))
    # Keep bars near maximum readable width; zoom still scales but less aggressively.
    max_bar_space = max(12, row_width - 24)
    zoom_scale = max(0.9, safe_zoom * 0.75)
    bar_width = max(12, min(max_bar_space, int(max_bar_space / zoom_scale)))
    ratio = clamp((value - gauge.min_value) / (gauge.max_value - gauge.min_value), 0.0, 1.0) if gauge.max_value > gauge.min_value else 0.0
    bar = render_regular_bar(ratio, bar_width)
    display_value = value_to_display(gauge, value, unit_preferences)
    unit_text = display_unit_for_gauge(gauge, unit_preferences)
    alert_text = state if state in {"WARN", "CRIT"} else ""
    return (
        f"{pointer} {gauge.label.upper():<12} {display_value:7.1f} {unit_text:<4} "
        f"[{bar}] {alert_text:<5}"
    )


def draw_interactive_dashboard(
    stdscr,
    gauges: Sequence[GaugeSpec],
    values: Dict[str, float],
    thresholds: Dict[str, GaugeThreshold],
    selected_index: int,
    selected_field: str,
    edit_mode: bool,
    edit_active: bool,
    edit_target: str,
    interval: float,
    zoom: float,
    message: str,
    use_color: bool,
    unit_preferences: UnitPreferences,
    theme: Dict[str, int],
) -> None:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    header_attr = theme["header"] if use_color else 0
    safe_addstr(stdscr, 0, 0, render_status_row(gauges, values, thresholds, interval, message)[:max_x], header_attr)

    if max_y < 14 or max_x < 60:
        safe_addstr(stdscr, 2, 0, "Terminal too small. Resize window for panel mode.")
        safe_addstr(stdscr, 3, 0, "Need at least 60x14.")
        stdscr.refresh()
        return

    layout = build_layout(max_y, max_x, edit_mode=edit_mode)
    draw_panel(
        stdscr,
        layout["main"],
        "Gauges",
        border_attr=theme["selected"] if edit_mode and edit_target == "selected" else theme["border"],
        title_attr=theme["title"],
    )
    draw_panel(
        stdscr,
        layout["speed"],
        "Speed",
        border_attr=theme["selected"] if edit_mode and edit_target == "speed" else theme["border"],
        title_attr=theme["title_focus"],
    )
    draw_panel(stdscr, layout["alerts"], "Alerts", border_attr=theme["border"], title_attr=theme["title"])
    if edit_mode:
        draw_panel(stdscr, layout["controls"], "Controls", border_attr=theme["border"], title_attr=theme["title"])

    draw_gauges_widget(
        stdscr,
        layout["main"],
        gauges,
        values,
        thresholds,
        selected_index,
        selected_field,
        edit_mode,
        edit_target,
        unit_preferences,
        zoom,
        theme,
    )
    draw_speed_widget(stdscr, layout["speed"], values, thresholds, selected_field, edit_mode, edit_active, edit_target, unit_preferences, zoom, theme)
    draw_alerts_widget(
        stdscr,
        layout["alerts"],
        gauges,
        values,
        thresholds,
        selected_index,
        selected_field,
        edit_mode,
        edit_active,
        edit_target,
        unit_preferences,
        theme,
    )
    if edit_mode:
        draw_controls_widget(
            stdscr,
            layout["controls"],
            gauges,
            selected_index,
            selected_field,
            edit_mode,
            edit_active,
            edit_target,
            interval,
            zoom,
            message,
            thresholds,
            unit_preferences,
            theme,
        )
    draw_footer(stdscr, layout["footer"], theme)

    stdscr.refresh()


def run_interactive(
    gauges: Sequence[GaugeSpec],
    thresholds: Dict[str, GaugeThreshold],
    unit_preferences: UnitPreferences,
    interval: float,
    config_path: str,
    demo: bool,
    client: OBDClient | None = None,
    zoom: float = 1.0,
) -> None:
    try:
        import curses
    except Exception as exc:
        raise RuntimeError(f"Interactive mode requires curses support: {exc}") from exc

    values: Dict[str, float] = {}
    selected_index = 0
    selected_field = "warning"
    edit_mode = False
    edit_active = False
    edit_target = "selected"
    message = "ready"

    def fetch_values() -> Dict[str, float]:
        if demo:
            return collect_demo_values()

        if client is None:
            return {}
        live_values = collect_live_values(client, gauges)
        if "speed" not in live_values and all(g.key != "speed" for g in gauges):
            try:
                speed_value = client.read_gauge(GAUGE_SPECS["speed"])
            except Exception:
                speed_value = None
            if speed_value is not None:
                live_values["speed"] = speed_value
        return live_values

    def loop(stdscr) -> None:
        nonlocal selected_index, selected_field, message, interval, values, edit_mode, edit_active, edit_target, unit_preferences, zoom

        curses.curs_set(0)
        stdscr.timeout(20)
        stdscr.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            if hasattr(curses, "mouseinterval"):
                curses.mouseinterval(0)
        except Exception:
            pass
        theme = init_curses_theme(curses)
        color_enabled = curses.has_colors()

        left_click_mask = (
            getattr(curses, "BUTTON1_CLICKED", 0)
            | getattr(curses, "BUTTON1_PRESSED", 0)
            | getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0)
        )
        right_click_mask = (
            getattr(curses, "BUTTON3_CLICKED", 0)
            | getattr(curses, "BUTTON3_PRESSED", 0)
            | getattr(curses, "BUTTON3_DOUBLE_CLICKED", 0)
        )
        wheel_up_mask = getattr(curses, "BUTTON4_PRESSED", 0) | getattr(curses, "BUTTON4_CLICKED", 0)
        wheel_down_mask = getattr(curses, "BUTTON5_PRESSED", 0) | getattr(curses, "BUTTON5_CLICKED", 0)

        def current_target_gauge() -> GaugeSpec:
            return GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]

        def tune_selected_threshold(direction: int) -> None:
            nonlocal message, edit_active
            gauge = current_target_gauge()
            step = threshold_step_base(gauge, unit_preferences)
            thresholds[gauge.key] = adjust_threshold(
                thresholds[gauge.key],
                gauge,
                selected_field,
                step if direction > 0 else -step,
            )
            edit_active = True
            sign = "+" if direction > 0 else "-"
            message = f"{gauge.label} {selected_field} {sign}"

        last_tick = 0.0
        while True:
            now = time.time()
            if now - last_tick >= interval:
                values = merge_latest_values(values, fetch_values())
                last_tick = now

            draw_interactive_dashboard(
                stdscr,
                gauges,
                values,
                thresholds,
                selected_index,
                selected_field,
                edit_mode,
                edit_active,
                edit_target,
                interval,
                zoom,
                message,
                use_color=color_enabled,
                unit_preferences=unit_preferences,
                theme=theme,
            )
            max_y, max_x = stdscr.getmaxyx()
            layout = build_layout(max_y, max_x, edit_mode=edit_mode)

            key = stdscr.getch()
            if key == -1:
                continue

            if key in (ord("q"), ord("Q")):
                break
            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except Exception:
                    message = "mouse event unavailable"
                    continue

                if bstate & left_click_mask:
                    if point_in_rect(my, mx, layout["main"]):
                        idx = gauge_index_from_mouse(my, layout["main"], len(gauges))
                        if idx is not None:
                            selected_index = idx
                        edit_mode = True
                        edit_target = "selected"
                        edit_active = True
                        message = f"mouse target {gauges[selected_index].label}"
                        continue
                    if point_in_rect(my, mx, layout["speed"]):
                        edit_mode = True
                        edit_target = "speed"
                        edit_active = True
                        message = "mouse target speed"
                        continue
                    if point_in_rect(my, mx, layout["controls"]):
                        edit_mode = True
                        edit_active = True
                        selected_field = "warning" if my < (layout["controls"].top + (layout["controls"].height // 2)) else "critical"
                        message = f"mouse field {selected_field}"
                        continue

                if bstate & right_click_mask:
                    selected_field = "critical" if selected_field == "warning" else "warning"
                    edit_mode = True
                    edit_active = True
                    message = f"mouse field {selected_field}"
                    continue

                if bstate & wheel_up_mask:
                    if not edit_mode:
                        message = "mouse wheel needs edit mode"
                        continue
                    tune_selected_threshold(1)
                    continue

                if bstate & wheel_down_mask:
                    if not edit_mode:
                        message = "mouse wheel needs edit mode"
                        continue
                    tune_selected_threshold(-1)
                    continue

            if key == curses.KEY_UP:
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                selected_index = (selected_index - 1) % len(gauges)
                message = f"selected {gauges[selected_index].label}"
            elif key == curses.KEY_DOWN:
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                selected_index = (selected_index + 1) % len(gauges)
                message = f"selected {gauges[selected_index].label}"
            elif key == 9:
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                if edit_active:
                    selected_field = "critical" if selected_field == "warning" else "warning"
                    message = f"field {selected_field}"
                else:
                    edit_target = "speed" if edit_target == "selected" else "selected"
                    target = "Speed" if edit_target == "speed" else gauges[selected_index].label
                    message = f"target {target}"
            elif key in (ord("w"), ord("W")):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                selected_field = "warning"
                message = "field warning"
            elif key in (ord("c"), ord("C")):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                selected_field = "critical"
                message = "field critical"
            elif key in (ord(","), ord("<")):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                if not edit_active:
                    edit_active = True
                gauge = GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]
                step = threshold_step_base(gauge, unit_preferences)
                thresholds[gauge.key] = adjust_threshold(thresholds[gauge.key], gauge, "critical", -step)
                selected_field = "critical"
                message = f"{gauge.label} critical -"
            elif key in (ord("."), ord(">")):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                if not edit_active:
                    edit_active = True
                gauge = GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]
                step = threshold_step_base(gauge, unit_preferences)
                thresholds[gauge.key] = adjust_threshold(thresholds[gauge.key], gauge, "critical", step)
                selected_field = "critical"
                message = f"{gauge.label} critical +"
            elif key in (10, 13, curses.KEY_ENTER):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                edit_active = not edit_active
                state = "editing" if edit_active else "edit-ready"
                message = state
            elif key in (ord("e"), ord("E")):
                edit_mode = not edit_mode
                if not edit_mode:
                    edit_active = False
                else:
                    edit_active = True
                message = "edit mode on" if edit_mode else "edit mode off"
            elif key in (ord("u"), ord("U")):
                unit_preferences = toggle_unit_preferences(unit_preferences)
                mode = "imperial" if unit_preferences.speed == "mph" else "metric"
                message = f"units {mode}"
            elif key in (ord("d"), ord("D")):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                if not edit_active:
                    edit_active = True
                gauge = GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]
                threshold = thresholds[gauge.key]
                new_direction = "low" if threshold.direction == "high" else "high"
                thresholds[gauge.key] = replace(threshold, direction=new_direction)
                message = f"{gauge.label} direction -> {new_direction}"
            elif key in (curses.KEY_RIGHT, ord("l"), ord("L"), ord("]")):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                if not edit_active:
                    edit_active = True
                gauge = GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]
                step = threshold_step_base(gauge, unit_preferences)
                thresholds[gauge.key] = adjust_threshold(thresholds[gauge.key], gauge, selected_field, step)
                message = f"{gauge.label} {selected_field} +"
            elif key in (curses.KEY_LEFT, ord("h"), ord("H"), ord("[")):
                if not edit_mode:
                    message = "press e for edit mode"
                    continue
                if not edit_active:
                    edit_active = True
                gauge = GAUGE_SPECS["speed"] if edit_target == "speed" else gauges[selected_index]
                step = threshold_step_base(gauge, unit_preferences)
                thresholds[gauge.key] = adjust_threshold(thresholds[gauge.key], gauge, selected_field, -step)
                message = f"{gauge.label} {selected_field} -"
            elif key == ord("+"):
                interval = max(0.05, interval - 0.02)
                message = f"interval {interval:.2f}s"
            elif key == ord("-"):
                interval = min(3.00, interval + 0.02)
                message = f"interval {interval:.2f}s"
            elif key in (ord("s"), ord("S")):
                try:
                    save_dashboard_config(config_path, thresholds, unit_preferences, zoom=zoom)
                    message = f"saved {config_path}"
                except Exception as exc:
                    message = f"save failed: {exc}"
            elif key in (ord("z"), ord("Z")):
                zoom = min(3.0, zoom + 0.1)
                message = f"zoom {zoom:.2f}x"
            elif key in (ord("x"), ord("X")):
                zoom = max(0.7, zoom - 0.1)
                message = f"zoom {zoom:.2f}x"

    curses.wrapper(loop)
