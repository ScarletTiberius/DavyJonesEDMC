"""
DavyJones EDMC Plugin
Integrates Elite Dangerous Market Connector with the Davy Jones Locker piracy squadron API.

Features (v1):
- On CMDR scan (ShipTargeted stage 3), checks the client list and shows status in the UI.
- Manual "Report Plunder" button opens a window with current cargo to mark loot and submit.
"""

import json
import logging
import os
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, ttk
from typing import Optional, Dict, Any, List, Tuple
from urllib import request as urlrequest, error as urlerror

import myNotebook as nb  # type: ignore  # provided by EDMC at runtime
from config import config  # type: ignore

try:
    from theme import theme  # type: ignore  # EDMC theme manager
except ImportError:
    theme = None  # graceful degradation if EDMC internals change

from cargo_window import CargoReportWindow
from stats_window import StatsWindow
from add_client_window import AddClientWindow
from clogging_window import CloggingWindow
import dj_theme as t
import overlay

PLUGIN_NAME = "DavyJones"
PLUGIN_VERSION = "0.1.0"
API_BASE_DEFAULT = "https://davyjones.org/api"
HTTP_TIMEOUT = 8  # seconds

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(PLUGIN_DIR, "icons")

logger = logging.getLogger(f"{PLUGIN_NAME}")


class ApiError(Exception):
    """Raised when an API call returns a non-2xx response.

    The server consistently returns:
        { "error": "<top-level message>", "details": { "errors": ["<line>", ...] } | null }

    This class carries the parsed structure so callers can present validation details
    instead of just dumping raw HTTP bodies.
    """

    def __init__(self, status: int, message: str, details: Optional[list] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or []

    def user_message(self) -> str:
        """Multi-line message suitable for showing in a dialog."""
        if not self.details:
            return self.message
        bullets = "\n".join(f"  • {line}" for line in self.details)
        return f"{self.message}\n\n{bullets}"

    def short_message(self) -> str:
        """One-line summary suitable for the overlay/HUD."""
        if not self.details:
            return self.message
        # First detail line as a hint; full text goes to the dialog
        return f"{self.message} ({self.details[0]})"


def _fmt_relative_time(iso_string: Any) -> str:
    """Format an ISO-8601 timestamp like '2025-12-17T21:23:44Z' as a relative duration
    ('8 days ago', '3 hours ago'). Falls back to the raw string if parsing fails so the user
    never sees an empty field, but most realistic inputs from our API will parse cleanly."""
    if not iso_string:
        return "—"
    raw = str(iso_string)
    # Handle 'Z' suffix that fromisoformat doesn't accept on Python < 3.11
    parseable = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(parseable)
    except (ValueError, TypeError):
        return raw  # show raw rather than guess
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"  # clock skew between client and server
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if seconds < 86400 * 30:
        d = seconds // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"
    if seconds < 86400 * 365:
        months = seconds // (86400 * 30)
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = seconds // (86400 * 365)
    return f"{years} year{'s' if years != 1 else ''} ago"


def _parse_api_error(status: int, body_bytes: bytes) -> ApiError:
    """Parse a server error response into an ApiError. Falls back gracefully if the body
    isn't the expected JSON shape (e.g. nginx 502, network proxy interception)."""
    try:
        body = json.loads(body_bytes.decode("utf-8", errors="replace") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ApiError(status, f"HTTP {status} (non-JSON response)")
    message = body.get("error") or f"HTTP {status}"
    details = None
    raw_details = body.get("details")
    if isinstance(raw_details, dict):
        errs = raw_details.get("errors")
        if isinstance(errs, list):
            details = [str(e) for e in errs]
    return ApiError(status, message, details)


def _load_icon(size: int) -> Optional[tk.PhotoImage]:
    """Load the icon at the given size, or None if unavailable."""
    path = os.path.join(ICON_DIR, f"davy_{size}_red.png")
    if not os.path.exists(path):
        return None
    try:
        return tk.PhotoImage(file=path)
    except tk.TclError:
        logger.exception(f"Failed to load icon {path}")
        return None


def _load_skull_icon(target_px: int = 20) -> Optional[tk.PhotoImage]:
    """Load target.png and scale it down to ~target_px square for use in a button."""
    path = os.path.join(ICON_DIR, "target.png")
    if not os.path.exists(path):
        return None
    try:
        img = tk.PhotoImage(file=path)
        factor = max(1, img.width() // target_px)
        return img.subsample(factor) if factor > 1 else img
    except tk.TclError:
        logger.exception("Failed to load skull icon")
        return None


class _Tooltip:
    """Minimal hover tooltip for any tk widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show, add=True)
        widget.bind("<Leave>", self._hide, add=True)

    def _show(self, event=None) -> None:
        if self._tip:
            return
        x = self._widget.winfo_rootx() + 10
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self._text,
            bg="#ffffe0", fg="#222222",
            relief="solid", borderwidth=1,
            font=("TkDefaultFont", 8), padx=4, pady=2,
        ).pack()

    def _hide(self, event=None) -> None:
        if self._tip:
            self._tip.destroy()
            self._tip = None


def _add_tooltip(widget: tk.Widget, text: str) -> None:
    _Tooltip(widget, text)


class PluginState:
    """Holds runtime state. EDMC plugins are module-level, so we wrap state here."""

    def __init__(self) -> None:
        self.api_base: str = ""
        self.api_key: str = ""
        self.cmdr: Optional[str] = None
        self.current_cargo: Dict[str, dict] = {}  # commodity_name -> count
        self.current_system: Optional[str] = None
        self.current_station: Optional[str] = None
        # List[Dict] — see _upsert_scan_entry for the schema. Session-scoped; never persisted.
        self.scan_history: List[Dict[str, Any]] = []
        # Dedup: (cmdr_name, monotonic_timestamp) of the last scan we API-checked.
        # Re-checking the same CMDR within this window is suppressed.
        self.last_lookup: Optional[Tuple[str, float]] = None

        # Cached profile from GET /api/me — populated on startup and after prefs save
        self._profile: Optional[Dict[str, Any]] = None

        # UI elements (created in plugin_app)
        self.status_label: Optional[tk.Label] = None
        self.network_label: Optional[tk.Label] = None
        self.scan_label: Optional[tk.Label] = None
        self.clogger_label: Optional[tk.Label] = None
        self.report_button: Optional[tk.Button] = None
        self.stats_button: Optional[tk.Button] = None
        self.add_client_button: Optional[tk.Button] = None
        self.clogger_button: Optional[tk.Button] = None
        self.parent_frame: Optional[tk.Frame] = None
        self.main_icon_image: Optional[tk.PhotoImage] = None  # GC pin
        self.prefs_icon_image: Optional[tk.PhotoImage] = None  # GC pin
        self.skull_icon_image: Optional[tk.PhotoImage] = None  # GC pin

        # Settings UI (created in plugin_prefs)
        self.api_base_var: Optional[tk.StringVar] = None
        self.api_key_var: Optional[tk.StringVar] = None
        self.show_api_key_var: Optional[tk.BooleanVar] = None
        self.theme_var: Optional[tk.StringVar] = None
        self.theme_enabled_var: Optional[tk.BooleanVar] = None
        self.theme_combo: Optional[ttk.Combobox] = None
        self.prefs_test_label: Optional[tk.Label] = None
        # Overlay toggles — master + 5 per-event. Persisted via EDMC config.
        self.overlay_master_var: Optional[tk.BooleanVar] = None
        self.overlay_scan_var: Optional[tk.BooleanVar] = None
        self.overlay_clogger_var: Optional[tk.BooleanVar] = None
        self.overlay_newtarget_var: Optional[tk.BooleanVar] = None
        self.overlay_plunder_var: Optional[tk.BooleanVar] = None
        self.overlay_client_var: Optional[tk.BooleanVar] = None
        self.overlay_ttl_scan_var: Optional[tk.StringVar] = None
        self.overlay_ttl_toast_var: Optional[tk.StringVar] = None
        # Settings entry widget refs (so the Show-API-key toggle can flip them)
        self.api_key_entry: Optional[tk.Entry] = None


state = PluginState()


# ---------------------------------------------------------------------------
# EDMC required hooks
# ---------------------------------------------------------------------------

def _get_bool_pref(key: str, default: bool = True) -> bool:
    """EDMC's config stores ints under string keys (no native bool); 1 = on, 0 = off, missing = default."""
    try:
        raw = config.get_int(key)
    except Exception:
        return default
    # get_int returns 0 for missing-or-unset, so we can't distinguish "off" from "never saved".
    # Workaround: use a sentinel marker key to know if the user has ever touched it.
    sentinel = config.get_int(key + "_set")
    if not sentinel:
        return default
    return bool(raw)


def _set_bool_pref(key: str, value: bool) -> None:
    config.set(key, 1 if value else 0)
    config.set(key + "_set", 1)


def _get_int_pref(key: str, default: int) -> int:
    try:
        raw = config.get_int(key)
    except Exception:
        return default
    return raw if raw > 0 else default


# Overlay toggle state cached in module-level vars for fast access on the hot path
_overlay_enabled = {
    "master": True,
    "scan": True,
    "clogger": True,
    "newtarget": False,  # default OFF — fires on every CMDR scan, noisier than other events
    "plunder": True,
    "client": True,
}


def _load_overlay_prefs() -> None:
    _overlay_enabled["master"] = _get_bool_pref("davyjones_overlay_master", True)
    _overlay_enabled["scan"] = _get_bool_pref("davyjones_overlay_scan", True)
    _overlay_enabled["clogger"] = _get_bool_pref("davyjones_overlay_clogger", True)
    _overlay_enabled["newtarget"] = _get_bool_pref("davyjones_overlay_newtarget", False)
    _overlay_enabled["plunder"] = _get_bool_pref("davyjones_overlay_plunder", True)
    _overlay_enabled["client"] = _get_bool_pref("davyjones_overlay_client", True)
    overlay.set_ttls(
        _get_int_pref("davyjones_overlay_ttl_scan", 6),
        _get_int_pref("davyjones_overlay_ttl_toast", 4),
    )


def _overlay_on(kind: str) -> bool:
    """Returns True iff the master is on AND the per-kind toggle is on."""
    return _overlay_enabled["master"] and _overlay_enabled.get(kind, True)


def plugin_start3(plugin_dir: str) -> str:
    """Called by EDMC on startup. Must return the plugin name."""
    state.api_base = config.get_str("davyjones_api_base") or API_BASE_DEFAULT
    state.api_key = config.get_str("davyjones_api_key") or ""
    _chosen_theme = config.get_str("davyjones_theme") or t.DEFAULT_THEME
    _theme_on = _get_bool_pref("davyjones_theme_enabled", True)
    t.apply_theme(_chosen_theme if _theme_on else "native")
    _load_overlay_prefs()
    logger.info(f"{PLUGIN_NAME} v{PLUGIN_VERSION} loaded")
    if overlay.is_available():
        logger.info("EDMCModernOverlay detected — HUD messages enabled")
    else:
        logger.info("No overlay plugin detected — HUD messages disabled")
    return PLUGIN_NAME


def plugin_stop() -> None:
    """Called by EDMC on shutdown."""
    logger.info(f"{PLUGIN_NAME} stopped")


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """Builds the plugin's UI section in the main EDMC window."""
    frame = tk.Frame(parent)
    state.parent_frame = frame

    # Logo + status header row
    state.main_icon_image = _load_icon(64)
    if state.main_icon_image is not None:
        icon_label = tk.Label(frame, image=state.main_icon_image)
        icon_label.grid(row=0, column=0, rowspan=4, sticky="nw", padx=(2, 6), pady=(8, 2))
        text_col_start = 1
    else:
        text_col_start = 0

    state.status_label = tk.Label(frame, text="DavyJones: ready", anchor="w")
    state.status_label.grid(row=0, column=text_col_start, columnspan=2, sticky="we")

    # Network connection info — populated async after startup/prefs save
    state.network_label = tk.Label(
        frame, text="○ not connected", anchor="w", fg="gray",
        font=("TkDefaultFont", 8),
    )
    state.network_label.grid(row=1, column=text_col_start, columnspan=2, sticky="we")

    # Show overlay availability subtly so users know whether HUD messages will appear
    overlay_text = "HUD: on" if overlay.is_available() else "HUD: off (install EDMCModernOverlay)"
    overlay_color = "green" if overlay.is_available() else "gray"
    overlay_label = tk.Label(
        frame, text=overlay_text, anchor="w", fg=overlay_color,
        font=("TkDefaultFont", 8),
    )
    overlay_label.grid(row=2, column=text_col_start, columnspan=2, sticky="we")

    tk.Label(frame, text="Last scan:", anchor="w").grid(
        row=3, column=text_col_start, sticky="w"
    )
    state.scan_label = tk.Label(frame, text="—", anchor="w", fg="gray")
    state.scan_label.grid(row=3, column=text_col_start + 1, sticky="we")

    state.clogger_label = tk.Label(frame, text="", anchor="w", fg="orange")
    # Not gridded initially — shown only when a clogger flag is active (see _set_clogger)

    # Action row: My Plunder | Report Plunder | Add Client | [skull] Report Clogger
    action_row = tk.Frame(frame)
    action_row.grid(
        row=5, column=0, columnspan=text_col_start + 2, sticky="we", pady=(4, 0)
    )

    state.stats_button = tk.Button(
        action_row, text="My Plunder", command=_open_stats_window
    )
    state.stats_button.pack(side="left", expand=True, fill="x", padx=(0, 2))
    _add_tooltip(state.stats_button, "your ledger entries and stats")

    state.report_button = tk.Button(
        action_row, text="Report Plunder", command=_open_report_window
    )
    state.report_button.pack(side="left", expand=True, fill="x", padx=(0, 2))
    _add_tooltip(state.report_button, "Tell us about your spoils, cmdr")

    state.add_client_button = tk.Button(
        action_row, text="Add Client", command=_open_add_client_window
    )
    state.add_client_button.pack(side="left", expand=True, fill="x", padx=(0, 2))
    _add_tooltip(state.add_client_button, "Give players that donated a pass")

    state.skull_icon_image = _load_skull_icon()
    if state.skull_icon_image:
        state.clogger_button = tk.Button(
            action_row, image=state.skull_icon_image, command=_open_clogging_window
        )
    else:
        state.clogger_button = tk.Button(
            action_row, text="⊕", command=_open_clogging_window
        )
    state.clogger_button.pack(side="left", padx=(0, 0))
    _add_tooltip(state.clogger_button, "Report Clogger — report players that combat logged")

    if theme is not None:
        for btn in (state.stats_button, state.add_client_button,
                    state.report_button, state.clogger_button):
            try:
                theme.register(btn)
            except Exception:
                logger.exception("Failed to register button with EDMC theme")

    frame.columnconfigure(text_col_start + 1, weight=1)

    # Fetch profile after the frame (and its labels) are fully wired into the widget tree.
    # plugin_start3 runs before plugin_app, so the label widget doesn't exist yet there.
    if state.api_key:
        frame.after(0, _fetch_profile_async)

    return frame


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> tk.Frame:
    """Builds the settings tab in EDMC's preferences."""
    frame = nb.Frame(parent)

    state.api_base_var = tk.StringVar(value=state.api_base)
    state.api_key_var = tk.StringVar(value=state.api_key)
    state.show_api_key_var = tk.BooleanVar(value=False)
    state.overlay_master_var = tk.BooleanVar(value=_overlay_enabled["master"])
    state.overlay_scan_var = tk.BooleanVar(value=_overlay_enabled["scan"])
    state.overlay_clogger_var = tk.BooleanVar(value=_overlay_enabled["clogger"])
    state.overlay_newtarget_var = tk.BooleanVar(value=_overlay_enabled["newtarget"])
    state.overlay_plunder_var = tk.BooleanVar(value=_overlay_enabled["plunder"])
    state.overlay_client_var = tk.BooleanVar(value=_overlay_enabled["client"])
    state.overlay_ttl_scan_var = tk.StringVar(value=str(_get_int_pref("davyjones_overlay_ttl_scan", 6)))
    state.overlay_ttl_toast_var = tk.StringVar(value=str(_get_int_pref("davyjones_overlay_ttl_toast", 4)))

    # --- Header: logo + plugin name/version ---
    header = nb.Frame(frame)
    header.grid(row=0, column=0, columnspan=2, sticky="we", padx=8, pady=(8, 8))

    state.prefs_icon_image = _load_icon(64)
    if state.prefs_icon_image is not None:
        nb.Label(header, image=state.prefs_icon_image).grid(
            row=0, column=0, rowspan=2, sticky="w", padx=(0, 12)
        )
    nb.Label(header, text="Davy Jones Locker").grid(row=0, column=1, sticky="w")
    nb.Label(header, text=f"EDMC plugin v{PLUGIN_VERSION}").grid(row=1, column=1, sticky="w")

    # --- API Connection ---
    ttk.Separator(frame, orient="horizontal").grid(
        row=1, column=0, columnspan=2, sticky="we", padx=8, pady=(8, 2)
    )
    nb.Label(frame, text="API Connection").grid(
        row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 4)
    )

    nb.Label(frame, text="Base URL:").grid(row=3, column=0, sticky="w", padx=8, pady=4)
    tk.Entry(frame, textvariable=state.api_base_var, width=40).grid(
        row=3, column=1, sticky="we", padx=8, pady=4
    )

    nb.Label(frame, text="API key:").grid(row=4, column=0, sticky="w", padx=8, pady=4)
    state.api_key_entry = tk.Entry(frame, textvariable=state.api_key_var, width=40, show="*")
    state.api_key_entry.grid(row=4, column=1, sticky="we", padx=8, pady=4)

    nb.Checkbutton(
        frame, text="Show API key",
        variable=state.show_api_key_var,
        command=_toggle_api_key_visibility,
    ).grid(row=5, column=1, sticky="w", padx=8, pady=(0, 2))

    # Test connection — nb.Frame with grid() children
    test_area = nb.Frame(frame)
    test_area.grid(row=6, column=1, sticky="w", padx=8, pady=(0, 4))
    tk.Button(
        test_area, text="Test Connection",
        command=_test_connection_from_prefs,
    ).grid(row=0, column=0, sticky="w")
    state.prefs_test_label = nb.Label(
        test_area, text="", wraplength=400, justify="left",
    )
    state.prefs_test_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

    nb.Label(
        frame,
        text="Get your API key from the Davy Jones Discord. Beta opt-in.",
    ).grid(row=7, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

    # --- Overlay ---
    ttk.Separator(frame, orient="horizontal").grid(
        row=8, column=0, columnspan=2, sticky="we", padx=8, pady=(8, 2)
    )
    nb.Label(frame, text="Overlay").grid(
        row=9, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 4)
    )

    nb.Checkbutton(
        frame, text="Enable overlay (master)",
        variable=state.overlay_master_var,
    ).grid(row=10, column=0, columnspan=2, sticky="w", padx=8)
    nb.Checkbutton(
        frame, text="Show scan results (known clients)",
        variable=state.overlay_scan_var,
    ).grid(row=11, column=0, columnspan=2, sticky="w", padx=(28, 8))
    nb.Checkbutton(
        frame, text="Show clogger scan results",
        variable=state.overlay_clogger_var,
    ).grid(row=12, column=0, columnspan=2, sticky="w", padx=(28, 8))
    nb.Checkbutton(
        frame, text="Show new-target scans (not in client list)",
        variable=state.overlay_newtarget_var,
    ).grid(row=13, column=0, columnspan=2, sticky="w", padx=(28, 8))
    nb.Checkbutton(
        frame, text="Show plunder confirmations",
        variable=state.overlay_plunder_var,
    ).grid(row=14, column=0, columnspan=2, sticky="w", padx=(28, 8))
    nb.Checkbutton(
        frame, text="Show client-add confirmations",
        variable=state.overlay_client_var,
    ).grid(row=15, column=0, columnspan=2, sticky="w", padx=(28, 8))

    nb.Label(frame, text="Duration (s):").grid(row=16, column=0, sticky="w", padx=8, pady=(6, 2))
    dur_row = tk.Frame(frame)
    dur_row.grid(row=16, column=1, sticky="w", padx=8, pady=(6, 2))
    nb.Label(dur_row, text="Scan:").pack(side="left")
    tk.Spinbox(dur_row, textvariable=state.overlay_ttl_scan_var,
               from_=1, to=30, width=3).pack(side="left", padx=(4, 2))
    nb.Label(dur_row, text="s").pack(side="left")
    nb.Label(dur_row, text="Toast:").pack(side="left", padx=(12, 0))
    tk.Spinbox(dur_row, textvariable=state.overlay_ttl_toast_var,
               from_=1, to=30, width=3).pack(side="left", padx=(4, 2))
    nb.Label(dur_row, text="s").pack(side="left")

    nb.Label(frame, text="Test:").grid(row=17, column=0, sticky="w", padx=8, pady=(8, 0))
    test_row = tk.Frame(frame)
    test_row.grid(row=17, column=1, sticky="w", padx=8, pady=(8, 4))

    _test_var = tk.StringVar(value=_TEST_OVERLAY_OPTIONS[0][0])
    ttk.Combobox(
        test_row,
        textvariable=_test_var,
        values=[name for name, _ in _TEST_OVERLAY_OPTIONS],
        state="readonly",
        width=26,
    ).pack(side="left", padx=(0, 6))

    def _fire_test():
        selected = _test_var.get()
        for name, fn in _TEST_OVERLAY_OPTIONS:
            if name == selected:
                fn()
                break

    tk.Button(test_row, text="Fire", command=_fire_test).pack(side="left")

    nb.Label(
        frame,
        text=(
            "Fires a sample message via EDMCModernOverlay (if installed) "
            "regardless of the per-event toggles above. Useful to verify position and styling."
        ),
        wraplength=480, justify="left",
    ).grid(row=18, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 8))

    # --- Appearance ---
    ttk.Separator(frame, orient="horizontal").grid(
        row=19, column=0, columnspan=2, sticky="we", padx=8, pady=(8, 2)
    )
    nb.Label(frame, text="Appearance").grid(
        row=20, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 4)
    )

    # Remember the user's chosen theme even while theming is off, so toggling it
    # back on restores their pick rather than leaving them on Plain.
    _chosen = config.get_str("davyjones_theme") or t.DEFAULT_THEME
    state.theme_enabled_var = tk.BooleanVar(value=_get_bool_pref("davyjones_theme_enabled", True))
    state.theme_var = tk.StringVar(value=t.label_for(_chosen))

    nb.Checkbutton(
        frame, text="Enable custom theme",
        variable=state.theme_enabled_var,
        command=_sync_theme_combo_state,
    ).grid(row=21, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 2))

    nb.Label(frame, text="Theme:").grid(row=22, column=0, sticky="w", padx=(28, 8), pady=4)
    state.theme_combo = ttk.Combobox(
        frame,
        textvariable=state.theme_var,
        values=[lbl for _, lbl in t.THEME_ORDER],
        state="readonly",
        width=26,
    )
    state.theme_combo.grid(row=22, column=1, sticky="w", padx=8, pady=4)
    nb.Label(
        frame,
        text="Colour scheme for the DavyJones popup windows. Applies the next time a window is opened. "
             "Uncheck to disable theming and follow your standard Windows colours instead.",
        wraplength=480, justify="left",
    ).grid(row=23, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
    _sync_theme_combo_state()  # grey out the dropdown if theming starts off

    # Attribution for third-party icons
    ttk.Separator(frame, orient="horizontal").grid(
        row=24, column=0, columnspan=2, sticky="we", padx=8, pady=(4, 2)
    )
    nb.Label(
        frame,
        text="Crosshair icons created by Creaticca Creative Agency · Flaticon (flaticon.com/free-icons/crosshair)",
        foreground="gray",
    ).grid(row=25, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 8))

    frame.columnconfigure(1, weight=1)
    return frame


def _toggle_api_key_visibility() -> None:
    """Flip the API key entry between masked and plain."""
    if not state.api_key_entry or not state.show_api_key_var:
        return
    state.api_key_entry.config(show="" if state.show_api_key_var.get() else "*")


def _sync_theme_combo_state() -> None:
    """Grey out the theme dropdown when custom theming is disabled."""
    if not state.theme_combo or not state.theme_enabled_var:
        return
    state.theme_combo.config(
        state="readonly" if state.theme_enabled_var.get() else "disabled"
    )


def _test_connection_from_prefs() -> None:
    """Test the API key/base currently entered in the prefs UI (not yet saved)."""
    if not state.api_base_var or not state.api_key_var or not state.prefs_test_label:
        return
    base = state.api_base_var.get().rstrip("/") or API_BASE_DEFAULT
    key = state.api_key_var.get().strip()
    if not key:
        state.prefs_test_label.config(text="✗  No API key entered.", foreground="red")
        return
    state.prefs_test_label.config(text="testing…", foreground="gray")

    def worker():
        try:
            req = urlrequest.Request(
                base + "/me",
                headers={
                    "X-API-Key": key,
                    "Accept": "application/json",
                    "User-Agent": f"DavyJonesEDMC/{PLUGIN_VERSION}",
                },
                method="GET",
            )
            with urlrequest.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                profile = json.loads(resp.read().decode("utf-8") or "{}")
            cmdr = profile.get("displayName") or profile.get("cmdr") or "?"
            guild = profile.get("guild") or "?"
            key_info = profile.get("key") or {}
            key_name = key_info.get("name", "—")
            created = _fmt_relative_time(key_info.get("createdAt"))
            expires_raw = key_info.get("expiresAt")
            expires = _fmt_relative_time(expires_raw) if expires_raw else "never"
            msg = (
                f"✓  {cmdr}  ·  {guild}\n"
                f"    Key: \"{key_name}\"  ·  created {created}  ·  expires {expires}"
            )
            if state.prefs_test_label:
                state.prefs_test_label.after(
                    0, lambda m=msg: state.prefs_test_label.config(text=m, foreground="green")
                )
        except urlerror.HTTPError as e:
            err = _parse_api_error(e.code, e.read() if e.fp else b"")
            msg = f"✗  {err.message}"
            if state.prefs_test_label:
                state.prefs_test_label.after(
                    0, lambda m=msg: state.prefs_test_label.config(text=m, foreground="red")
                )
        except Exception as e:
            msg = f"✗  connection error: {e}"
            if state.prefs_test_label:
                state.prefs_test_label.after(
                    0, lambda m=msg: state.prefs_test_label.config(text=m, foreground="red")
                )

    threading.Thread(target=worker, daemon=True).start()


def _test_overlay_known() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_scan_result("TEST CMDR", "KNOWN CLIENT", subtext="robbed 3x - last 8 days ago", color=overlay.COLOR_GREEN)


def _test_overlay_cooldown() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_scan_result("TEST CMDR", "ON COOLDOWN", subtext="last robbed 2 hours ago", color=overlay.COLOR_AMBER)


def _test_clogger_mild() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_scan_result("TEST CMDR", _clogger_overlay_label(3), subtext="score 3 (1 report(s))", color=overlay.COLOR_RED)


def _test_clogger_moderate() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_scan_result("TEST CMDR", _clogger_overlay_label(8), subtext="score 8 (3 report(s))", color=overlay.COLOR_RED)


def _test_clogger_severe() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_scan_result("TEST CMDR", _clogger_overlay_label(20), subtext="score 20 (7 report(s))", color=overlay.COLOR_RED)


def _test_overlay_client_clogger() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_scan_result("TEST CMDR", _clogger_overlay_label(8), subtext="robbed 2x + score 8", color=overlay.COLOR_RED)


def _test_overlay_newtarget() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_scan_result("TEST CMDR", "NEW TARGET", subtext="no record found", color=overlay.COLOR_BLUE)


def _overlay_not_available_msg() -> None:
    messagebox.showinfo(
        "DavyJones",
        "Overlay not detected. Install EDMCModernOverlay to use HUD messages.",
    )


def _test_overlay_toast_plunder_ok() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_toast("PLUNDER LOGGED", subtext="47t across 3 item(s) (PvP)", color=overlay.COLOR_GREEN)


def _test_overlay_toast_plunder_fail() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_toast("PLUNDER FAILED", subtext="HTTP 500", color=overlay.COLOR_RED)


def _test_overlay_toast_client_added() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_toast("CLIENT ADDED", subtext="TEST CMDR (hatchbreak)", color=overlay.COLOR_GREEN)


def _test_overlay_toast_duplicate() -> None:
    if not overlay.is_available():
        _overlay_not_available_msg()
        return
    overlay.show_toast("ALREADY IN COOLDOWN", subtext="TEST CMDR", color=overlay.COLOR_AMBER)


_TEST_OVERLAY_OPTIONS = [
    ("Scan: known client",        _test_overlay_known),
    ("Scan: cooldown",            _test_overlay_cooldown),
    ("Scan: new target",          _test_overlay_newtarget),
    ("Scan: clogger (mild)",      _test_clogger_mild),
    ("Scan: clogger (moderate)",  _test_clogger_moderate),
    ("Scan: clogger (severe)",    _test_clogger_severe),
    ("Scan: client + clogger",    _test_overlay_client_clogger),
    ("Toast: plunder ok",      _test_overlay_toast_plunder_ok),
    ("Toast: plunder fail",    _test_overlay_toast_plunder_fail),
    ("Toast: client added",    _test_overlay_toast_client_added),
    ("Toast: duplicate",       _test_overlay_toast_duplicate),
]


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    """Called by EDMC when prefs are saved."""
    if state.api_base_var:
        state.api_base = state.api_base_var.get().rstrip("/") or API_BASE_DEFAULT
        config.set("davyjones_api_base", state.api_base)
    if state.api_key_var:
        state.api_key = state.api_key_var.get().strip()
        config.set("davyjones_api_key", state.api_key)
    # Persist overlay toggles
    for key, var_name in [
        ("master", "overlay_master_var"),
        ("scan", "overlay_scan_var"),
        ("clogger", "overlay_clogger_var"),
        ("newtarget", "overlay_newtarget_var"),
        ("plunder", "overlay_plunder_var"),
        ("client", "overlay_client_var"),
    ]:
        var = getattr(state, var_name, None)
        if var is not None:
            value = bool(var.get())
            _overlay_enabled[key] = value
            _set_bool_pref(f"davyjones_overlay_{key}", value)
    # Persist and apply overlay display durations
    def _parse_ttl(var_name: str, default: int) -> int:
        var = getattr(state, var_name, None)
        try:
            return max(1, int(var.get())) if var else default
        except (ValueError, TypeError):
            return default
    ttl_scan = _parse_ttl("overlay_ttl_scan_var", 6)
    ttl_toast = _parse_ttl("overlay_ttl_toast_var", 4)
    config.set("davyjones_overlay_ttl_scan", ttl_scan)
    config.set("davyjones_overlay_ttl_toast", ttl_toast)
    overlay.set_ttls(ttl_scan, ttl_toast)
    # Persist and apply the selected theme (takes effect on the next window open).
    # The chosen theme is always remembered; when theming is disabled we just
    # apply Plain instead, leaving the saved pick intact for when it's re-enabled.
    if state.theme_var:
        theme_key = t.key_for(state.theme_var.get())
        config.set("davyjones_theme", theme_key)
        theme_on = bool(state.theme_enabled_var.get()) if state.theme_enabled_var else True
        _set_bool_pref("davyjones_theme_enabled", theme_on)
        t.apply_theme(theme_key if theme_on else "native")
    _set_status("Settings saved")
    # Re-fetch profile with the (possibly changed) key/base
    if state.api_key:
        _fetch_profile_async()
    else:
        _set_network_label("○ no API key", color="gray")


def journal_entry(
    cmdr: str,
    is_beta: bool,
    system: str,
    station: str,
    entry: Dict[str, Any],
    state_dict: Dict[str, Any],
) -> Optional[str]:
    """Called by EDMC for every journal event."""
    state.cmdr = cmdr
    state.current_system = system or None
    state.current_station = station or None
    event = entry.get("event")

    if event == "ShipTargeted":
        _handle_ship_targeted(entry)
    elif event == "Cargo":
        _handle_cargo(entry)

    return None


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_ship_targeted(entry: Dict[str, Any]) -> None:
    """ShipTargeted fires at each scan stage.
    Stage 2 gives PilotName (CMDR name); Stage 3 adds PilotRank (combat rank).
    In practice the game sometimes skips straight to stage 3 (close range / fast scan),
    so we trigger the API lookup at either stage and rely on the 30-second cooldown to
    deduplicate when both stages do fire.
    Stage 3 occasionally arrives without PilotName (the game doesn't repeat it when stage 2
    already sent it). In that case we fall back to last_lookup to store the rank."""
    if not entry.get("TargetLocked"):
        return
    stage = entry.get("ScanStage", 0)
    if stage < 2:
        return

    pilot_name = entry.get("PilotName") or ""
    if pilot_name.startswith("$cmdr_decorate:#name="):
        # Format is "$cmdr_decorate:#name=ROHAN DEX;" — strip the wrapper
        cmdr_name = pilot_name.replace("$cmdr_decorate:#name=", "").rstrip(";").strip() or None
    else:
        cmdr_name = None

    # Stage 3 sometimes arrives without PilotName. If we have PilotRank and a recent
    # last_lookup, use that CMDR name so the rank is not silently dropped.
    if cmdr_name is None and stage == 3 and entry.get("PilotRank") and state.last_lookup:
        if (time.monotonic() - state.last_lookup[1]) < 30:
            cmdr_name = state.last_lookup[0]

    if not cmdr_name:
        # NPC or unrecognised format — skip
        return

    _upsert_scan_entry(cmdr_name)

    if stage == 3:
        pilot_rank = entry.get("PilotRank")
        if pilot_rank:
            record = get_scanned_cmdr(cmdr_name)
            if record is not None:
                record["combat_rank"] = pilot_rank

    # Trigger lookup at stage 2 or 3; cooldown deduplicates if both stages fire
    now = time.monotonic()
    if state.last_lookup and state.last_lookup[0] == cmdr_name and (now - state.last_lookup[1]) < 30:
        return
    state.last_lookup = (cmdr_name, now)
    logger.debug(f"ShipTargeted stage {stage}: looking up {cmdr_name!r}")
    _lookup_client_async(cmdr_name)


def _upsert_scan_entry(cmdr_name: str) -> None:
    """Add a new scan-history entry or refresh an existing one in place."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = get_scanned_cmdr(cmdr_name)
    if existing is not None:
        existing["system"] = state.current_system
        existing["station"] = state.current_station
        existing["scanned_at"] = now_iso
    else:
        if len(state.scan_history) >= 50:
            oldest = min(range(len(state.scan_history)), key=lambda i: state.scan_history[i]["scanned_at"])
            state.scan_history.pop(oldest)
        state.scan_history.append({
            "cmdr": cmdr_name,
            "combat_rank": None,
            "system": state.current_system,
            "station": state.current_station,
            "scanned_at": now_iso,
        })


def get_scanned_cmdr(name: str) -> Optional[Dict[str, Any]]:
    """Return the scan-history record for *name*, or None. Case-insensitive."""
    lower = name.lower()
    for record in state.scan_history:
        if record["cmdr"].lower() == lower:
            return record
    return None


def _recent_scans_desc() -> List[Dict[str, Any]]:
    """A copy of the scan history, most-recently-scanned first. scan_history is in
    insertion order and re-scans refresh the timestamp in place without moving the
    entry, so we sort by `scanned_at` (ISO UTC, lexicographically sortable)."""
    return sorted(
        state.scan_history,
        key=lambda r: r.get("scanned_at", ""),
        reverse=True,
    )


def _handle_cargo(entry: Dict[str, Any]) -> None:
    """Cargo events come in two flavors: with Inventory inline, or just a count
    referencing the Cargo.json file. We handle both."""
    inventory = entry.get("Inventory")
    if inventory is None:
        # Bare event ({"event":"Cargo","Count":N}). Read the companion file.
        inventory = _read_cargo_json()
        if inventory is None:
            return
    _set_cargo_from_inventory(inventory)

def _set_cargo_from_inventory(inventory: list) -> None:
    """Common path — accept an inventory list (from journal Inventory or Cargo.json) and
    populate state.current_cargo with FDevID-keyed entries."""
    state.current_cargo = {
        item.get("Name", "?"): {
            "count": int(item.get("Count", 0)),
            "display": item.get("Name_Localised") or item.get("Name", "?"),
        }
        for item in inventory
        if item.get("Count", 0) > 0
    }


def _read_cargo_json() -> Optional[list]:
    """Read Cargo.json from ED's journal directory. Returns the Inventory list or None."""
    try:
        journal_dir = config.get_str("journaldir") or ""
    except Exception:
        journal_dir = ""
    if not journal_dir:
        journal_dir = os.path.join(
            os.path.expanduser("~"),
            "Saved Games", "Frontier Developments", "Elite Dangerous",
        )
    path = os.path.join(journal_dir, "Cargo.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        inv = data.get("Inventory")
        if isinstance(inv, list):
            return inv
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        logger.exception(f"Failed to read {path}")
    return None

# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def _clogger_overlay_label(score: int) -> str:
    """EDR-style plus-grade for clogger severity — more plusses = worse.
    Mirrors EDR's `Outlaw++++` karma convention so the HUD reads at a glance.
    The EDMC sidebar label keeps the spelled-out MILD/moderate/SEVERE wording."""
    if score >= 15:
        plus = "++++"
    elif score >= 6:
        plus = "+++"
    elif score >= 3:
        plus = "++"
    else:
        plus = "+"
    return f"CLOGGER{plus}"


def _lookup_client_async(cmdr_name: str) -> None:
    """Fire off the lookup in a background thread so we don't block journal processing."""
    if not state.api_key:
        _set_scan(cmdr_name, "no API key configured", color="orange")
        return
    _set_scan(cmdr_name, "checking…", color="gray")
    threading.Thread(
        target=_lookup_client_worker, args=(cmdr_name,), daemon=True
    ).start()


def _lookup_client_worker(cmdr_name: str) -> None:
    try:
        result = _api_get(f"/clients/{urlrequest.quote(cmdr_name)}")
    except ApiError as e:
        if e.status == 404:
            _set_scan(cmdr_name, "unknown", color="gray")
            if _overlay_on("newtarget"):
                overlay.show_scan_result(
                    cmdr_name, "NEW TARGET",
                    subtext="no record found",
                    color=overlay.COLOR_BLUE,
                )
            return
        logger.warning(f"Client lookup failed for {cmdr_name}: {e.status} {e.message}")
        _set_scan(cmdr_name, f"lookup failed ({e.status})", color="red")
        if _overlay_on("scan"):
            overlay.show_scan_result(
                cmdr_name, "LOOKUP FAILED",
                subtext=e.message[:60],
                color=overlay.COLOR_RED,
            )
        return
    except Exception as e:
        logger.exception("Client lookup failed")
        _set_scan(cmdr_name, f"lookup failed: {e}", color="red")
        if _overlay_on("scan"):
            overlay.show_scan_result(
                cmdr_name, "LOOKUP FAILED",
                subtext="connection error",
                color=overlay.COLOR_RED,
            )
        return

    if not result:
        _set_scan(cmdr_name, "unknown", color="gray")
        return

    client = result.get("client") or {}
    clogger = result.get("clogger") or {}

    on_cooldown = False
    last_robbed = ""
    times_robbed = 0
    if client:
        on_cooldown = bool(client.get("onCooldown"))
        last_robbed = _fmt_relative_time(client.get("lastRobbedAt"))
        times_robbed = client.get("timesRobbed", 0)

    clogger_score = clogger.get("score", 0) if clogger else 0
    is_clogger = clogger_score > 0

    # --- EDMC panel ---
    # Clogger overrides scan-label colour even when client info is present.
    if client:
        client_msg = (
            f"⛔ ON COOLDOWN — last robbed {last_robbed}" if on_cooldown
            else f"✓ client (robbed {times_robbed}×, last {last_robbed})"
        )
        panel_color = "red" if is_clogger else ("orange" if on_cooldown else "green")
        _set_scan(cmdr_name, client_msg, color=panel_color)
    else:
        _set_scan(cmdr_name, "no client record", color="gray")

    if is_clogger:
        if clogger_score >= 15:
            _set_clogger(f"⚠ CLOGGER — SEVERE (score {clogger_score})", color="red")
        elif clogger_score >= 5:
            _set_clogger(f"⚠ CLOGGER — moderate (score {clogger_score})", color="orange")
        else:
            _set_clogger(f"⚠ CLOGGER — mild (score {clogger_score})", color="#e6a800")

    # --- Overlay: clogger (red) > cooldown (amber) > known client (green) ---
    if is_clogger:
        ov_header = _clogger_overlay_label(clogger_score)
        if client:
            ov_sub = (
                f"cooldown active + score {clogger_score}" if on_cooldown
                else f"robbed {times_robbed}x + score {clogger_score}"
            )
        else:
            ov_sub = f"score {clogger_score} ({clogger.get('reportCount', 0)} report(s))"
        if _overlay_on("clogger"):
            overlay.show_scan_result(cmdr_name, ov_header, subtext=ov_sub, color=overlay.COLOR_RED)
    elif client:
        if on_cooldown:
            if _overlay_on("scan"):
                overlay.show_scan_result(cmdr_name, "ON COOLDOWN", subtext=f"last robbed {last_robbed}", color=overlay.COLOR_AMBER)
        else:
            if _overlay_on("scan"):
                overlay.show_scan_result(cmdr_name, "KNOWN CLIENT", subtext=f"robbed {times_robbed}x - last {last_robbed}", color=overlay.COLOR_GREEN)


def submit_plunder(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Called from the cargo window. Synchronous because the window blocks anyway.
    Payload comes in with snake_case (`kind`, `items`, `count`, `commodity`); we map it
    to the camelCase shape the server expects (`Kind`, `Items`, `Count`, `Commodity`)."""
    if not state.api_key:
        return False, "No API key configured."

    server_payload = {
        "Kind": payload.get("kind"),
        "Items": [
            {"Commodity": item.get("commodity"), "Count": item.get("count")}
            for item in (payload.get("items") or [])
        ],
    }

    try:
        result = _api_post("/me/plunder", server_payload)
    except ApiError as e:
        if _overlay_on("plunder"):
            overlay.show_toast(
                "PLUNDER FAILED",
                subtext=f"HTTP {e.status}", color=overlay.COLOR_RED,
            )
        return False, e.user_message()
    except Exception as e:
        if _overlay_on("plunder"):
            overlay.show_toast(
                "PLUNDER FAILED",
                subtext="connection error", color=overlay.COLOR_RED,
            )
        return False, str(e)

    # Server returns {"reported": N} — number of line items accepted
    reported_count = (result or {}).get("reported", len(server_payload["Items"]))
    items = payload.get("items") or []
    total_tonnage = sum(int(i.get("count", 0)) for i in items)
    kind = payload.get("kind", "")
    if _overlay_on("plunder"):
        overlay.show_toast(
            "PLUNDER LOGGED",
            subtext=f"{total_tonnage}t across {reported_count} item(s) ({kind})",
            color=overlay.COLOR_GREEN,
        )
    return True, f"Plunder reported ({reported_count} item(s))."


def fetch_stats() -> Optional[Dict[str, Any]]:
    """Called from the stats window. Synchronous (the window already runs this in a thread).
    The API key identifies the CMDR server-side, so no name is sent."""
    if not state.api_key:
        raise RuntimeError("No API key configured.")
    try:
        return _api_get("/me/stats")
    except ApiError as e:
        # The stats window catches any Exception and shows its str() — give it a useful one
        raise RuntimeError(e.user_message()) from e


def submit_add_client(cmdr_name: str, complied: bool) -> Tuple[bool, str]:
    """Add a CMDR to the squadron client list. Synchronous from the caller's perspective."""
    if not state.api_key:
        return False, "No API key configured."
    if not cmdr_name or not cmdr_name.strip():
        return False, "Commander name is required."
    payload = {
        "CmdrName": cmdr_name.strip(),
        "Complied": complied,
    }
    try:
        _api_post("/clients", payload)
    except ApiError as e:
        if e.status == 409:
            if _overlay_on("client"):
                overlay.show_toast(
                    "ALREADY IN COOLDOWN",
                    subtext=cmdr_name, color=overlay.COLOR_AMBER,
                )
            return False, e.message  # server's wording is already clear
        if _overlay_on("client"):
            overlay.show_toast(
                "ADD CLIENT FAILED",
                subtext=f"HTTP {e.status}", color=overlay.COLOR_RED,
            )
        return False, e.user_message()
    except Exception as e:
        if _overlay_on("client"):
            overlay.show_toast(
                "ADD CLIENT FAILED",
                subtext="connection error", color=overlay.COLOR_RED,
            )
        return False, str(e)

    outcome_label = "complied" if complied else "hatchbreak"
    if _overlay_on("client"):
        overlay.show_toast(
            "CLIENT ADDED",
            subtext=f"{cmdr_name} ({outcome_label})",
            color=overlay.COLOR_GREEN,
        )
    return True, f"Added {cmdr_name} to the client list."


def submit_clogging_report(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Called from CloggingWindow. Synchronous from caller's perspective (window runs it in a thread)."""
    if not state.api_key:
        return False, "No API key configured."
    try:
        _api_post("/clogging", payload)
    except ApiError as e:
        if e.status == 409:
            return False, e.message  # server's wording is already descriptive
        return False, e.user_message()
    except Exception as e:
        return False, str(e)
    return True, f"Report submitted for {payload.get('targetCmdr', 'CMDR')}."


def fetch_clogging_reports() -> List[Dict[str, Any]]:
    """Called from CloggingWindow. The window already runs this in a thread."""
    if not state.api_key:
        raise RuntimeError("No API key configured.")
    try:
        result = _api_get("/me/clogging-reports")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("reports") or []
        return []
    except ApiError as e:
        raise RuntimeError(e.user_message()) from e


def update_clogging_report(
    report_id: int, proof_url: Optional[str], shared: bool
) -> Tuple[bool, str]:
    """Called from CloggingWindow. The window already runs this in a thread."""
    if not state.api_key:
        return False, "No API key configured."
    payload = {"proofUrl": proof_url, "shared": shared}
    try:
        _api_put(f"/clogging/{report_id}", payload)
    except ApiError as e:
        return False, e.user_message()
    except Exception as e:
        return False, str(e)
    return True, "Report updated."


def _api_get(path: str) -> Optional[Dict[str, Any]]:
    req = urlrequest.Request(
        state.api_base + path,
        headers={
            "X-API-Key": state.api_key,
            "Accept": "application/json",
            "User-Agent": f"DavyJonesEDMC/{PLUGIN_VERSION}",
        },
        method="GET",
    )
    try:
        with urlrequest.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urlerror.HTTPError as e:
        raise _parse_api_error(e.code, e.read() if e.fp else b"") from e


def _api_post(path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        state.api_base + path,
        data=data,
        headers={
            "X-API-Key": state.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"DavyJonesEDMC/{PLUGIN_VERSION}",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urlerror.HTTPError as e:
        raise _parse_api_error(e.code, e.read() if e.fp else b"") from e


def _api_put(path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        state.api_base + path,
        data=data,
        headers={
            "X-API-Key": state.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"DavyJonesEDMC/{PLUGIN_VERSION}",
        },
        method="PUT",
    )
    try:
        with urlrequest.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urlerror.HTTPError as e:
        raise _parse_api_error(e.code, e.read() if e.fp else b"") from e


# ---------------------------------------------------------------------------
# UI helpers (thread-safe via after())
# ---------------------------------------------------------------------------

def _set_status(text: str) -> None:
    if state.status_label:
        state.status_label.after(0, lambda: state.status_label.config(text=f"DavyJones: {text}"))


def _set_network_label(text: str, color: str = "gray") -> None:
    if state.network_label:
        state.network_label.after(0, lambda t=text, c=color: state.network_label.config(text=t, fg=c))


def _fetch_profile_async() -> None:
    _set_network_label("● connecting…", color="gray")
    threading.Thread(target=_fetch_profile_worker, daemon=True).start()


def _fetch_profile_worker() -> None:
    try:
        profile = _api_get("/me")
        state._profile = profile
        if profile:
            cmdr = profile.get("displayName") or profile.get("cmdr") or "?"
            guild = profile.get("guild") or "unknown squadron"
            _set_network_label(f"● {cmdr}  ·  {guild}", color="green")
        else:
            _set_network_label("○ no profile returned", color="gray")
    except ApiError as e:
        _set_network_label(f"○ auth failed ({e.status})", color="red")
    except Exception:
        logger.exception("Profile fetch failed")
        _set_network_label("○ not connected", color="gray")


def _set_scan(cmdr_name: str, text: str, color: str = "black") -> None:
    if state.scan_label:
        state.scan_label.after(
            0,
            lambda: state.scan_label.config(text=f"{cmdr_name}: {text}", fg=color),
        )
    if state.clogger_label:
        state.clogger_label.after(0, lambda: state.clogger_label.grid_remove())


def _set_clogger(text: str, color: str = "orange") -> None:
    if not state.clogger_label:
        return
    col = 1 if state.main_icon_image else 0

    def _update():
        state.clogger_label.config(text=text, fg=color)
        state.clogger_label.grid(row=4, column=col, columnspan=2, sticky="we")

    state.clogger_label.after(0, _update)

def _open_report_window() -> None:
    if not state.parent_frame:
        return
    if not state.api_key:
        messagebox.showwarning(
            "DavyJones", "No API key configured. Set one in Settings → DavyJones."
        )
        return
    # Refresh cargo from Cargo.json — it's always current, the journal Inventory isn't
    inv = _read_cargo_json()
    if inv is not None:
        _set_cargo_from_inventory(inv)
    CargoReportWindow(
        parent=state.parent_frame.winfo_toplevel(),
        cargo=dict(state.current_cargo),
        cmdr=state.cmdr or "",
        submit_callback=submit_plunder,
    )

def _open_stats_window() -> None:
    if not state.parent_frame:
        return
    if not state.api_key:
        messagebox.showwarning(
            "DavyJones", "No API key configured. Set one in Settings → DavyJones."
        )
        return
    StatsWindow(
        parent=state.parent_frame.winfo_toplevel(),
        cmdr=state.cmdr or "",
        fetch_callback=fetch_stats,
    )


def _open_add_client_window() -> None:
    if not state.parent_frame:
        return
    if not state.api_key:
        messagebox.showwarning(
            "DavyJones", "No API key configured. Set one in Settings → DavyJones."
        )
        return
    AddClientWindow(
        parent=state.parent_frame.winfo_toplevel(),
        cmdr=state.cmdr or "",
        scan_history=_recent_scans_desc(),
        submit_callback=submit_add_client,
    )


def _open_clogging_window() -> None:
    if not state.parent_frame:
        return
    if not state.api_key:
        messagebox.showwarning(
            "DavyJones", "No API key configured. Set one in Settings → DavyJones."
        )
        return
    CloggingWindow(
        parent=state.parent_frame.winfo_toplevel(),
        cmdr=state.cmdr or "",
        scan_history=_recent_scans_desc(),
        submit_callback=submit_clogging_report,
        fetch_reports_callback=fetch_clogging_reports,
        update_callback=update_clogging_report,
    )
