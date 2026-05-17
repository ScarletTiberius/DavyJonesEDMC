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
from tkinter import messagebox
from typing import Optional, Dict, Any, Tuple
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


class PluginState:
    """Holds runtime state. EDMC plugins are module-level, so we wrap state here."""

    def __init__(self) -> None:
        self.api_base: str = ""
        self.api_key: str = ""
        self.cmdr: Optional[str] = None
        self.current_cargo: Dict[str, dict] = {}  # commodity_name -> count
        self.scan_history: list = []  # List[str] of CMDR names, most recent first, deduped
        # Dedup: (cmdr_name, monotonic_timestamp) of the last scan we API-checked.
        # Re-checking the same CMDR within this window is suppressed.
        self.last_lookup: Optional[Tuple[str, float]] = None

        # UI elements (created in plugin_app)
        self.status_label: Optional[tk.Label] = None
        self.scan_label: Optional[tk.Label] = None
        self.report_button: Optional[tk.Button] = None
        self.stats_button: Optional[tk.Button] = None
        self.add_client_button: Optional[tk.Button] = None
        self.parent_frame: Optional[tk.Frame] = None
        self.main_icon_image: Optional[tk.PhotoImage] = None  # GC pin
        self.prefs_icon_image: Optional[tk.PhotoImage] = None  # GC pin

        # Settings UI (created in plugin_prefs)
        self.api_base_var: Optional[tk.StringVar] = None
        self.api_key_var: Optional[tk.StringVar] = None
        self.show_api_key_var: Optional[tk.BooleanVar] = None
        # Overlay toggles — master + 4 per-event. Persisted via EDMC config.
        self.overlay_master_var: Optional[tk.BooleanVar] = None
        self.overlay_scan_var: Optional[tk.BooleanVar] = None
        self.overlay_newtarget_var: Optional[tk.BooleanVar] = None
        self.overlay_plunder_var: Optional[tk.BooleanVar] = None
        self.overlay_client_var: Optional[tk.BooleanVar] = None
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


# Overlay toggle state cached in module-level vars for fast access on the hot path
_overlay_enabled = {
    "master": True,
    "scan": True,
    "newtarget": False,  # default OFF — fires on every CMDR scan, noisier than other events
    "plunder": True,
    "client": True,
}


def _load_overlay_prefs() -> None:
    _overlay_enabled["master"] = _get_bool_pref("davyjones_overlay_master", True)
    _overlay_enabled["scan"] = _get_bool_pref("davyjones_overlay_scan", True)
    _overlay_enabled["newtarget"] = _get_bool_pref("davyjones_overlay_newtarget", False)
    _overlay_enabled["plunder"] = _get_bool_pref("davyjones_overlay_plunder", True)
    _overlay_enabled["client"] = _get_bool_pref("davyjones_overlay_client", True)


def _overlay_on(kind: str) -> bool:
    """Returns True iff the master is on AND the per-kind toggle is on."""
    return _overlay_enabled["master"] and _overlay_enabled.get(kind, True)


def plugin_start3(plugin_dir: str) -> str:
    """Called by EDMC on startup. Must return the plugin name."""
    state.api_base = config.get_str("davyjones_api_base") or API_BASE_DEFAULT
    state.api_key = config.get_str("davyjones_api_key") or ""
    _load_overlay_prefs()
    logger.info(f"{PLUGIN_NAME} v{PLUGIN_VERSION} loaded")
    # Probe overlay availability on startup so it's reflected in the UI
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
        icon_label.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(2, 6), pady=2)
        text_col_start = 1
    else:
        text_col_start = 0

    state.status_label = tk.Label(frame, text="DavyJones: ready", anchor="w")
    state.status_label.grid(row=0, column=text_col_start, columnspan=2, sticky="we")

    # Show overlay availability subtly so users know whether HUD messages will appear
    overlay_text = "HUD: on" if overlay.is_available() else "HUD: off (install EDMCModernOverlay)"
    overlay_color = "green" if overlay.is_available() else "gray"
    overlay_label = tk.Label(
        frame, text=overlay_text, anchor="w", fg=overlay_color,
        font=("TkDefaultFont", 8),
    )
    overlay_label.grid(row=1, column=text_col_start, columnspan=2, sticky="we")

    tk.Label(frame, text="Last scan:", anchor="w").grid(
        row=2, column=text_col_start, sticky="w"
    )
    state.scan_label = tk.Label(frame, text="—", anchor="w", fg="gray")
    state.scan_label.grid(row=2, column=text_col_start + 1, sticky="we")

    # All three actions on a single row — fits at default EDMC width
    button_row = tk.Frame(frame)
    button_row.grid(
        row=3, column=0, columnspan=text_col_start + 2, sticky="we", pady=(4, 0)
    )
    state.stats_button = tk.Button(
        button_row, text="My Stats", command=_open_stats_window
    )
    state.stats_button.pack(side="left", expand=True, fill="x", padx=(0, 2))
    state.add_client_button = tk.Button(
        button_row, text="Add Client", command=_open_add_client_window
    )
    state.add_client_button.pack(side="left", expand=True, fill="x", padx=(2, 2))
    state.report_button = tk.Button(
        button_row, text="Report Plunder", command=_open_report_window
    )
    state.report_button.pack(side="left", expand=True, fill="x", padx=(2, 0))

    if theme is not None:
        for btn in (state.stats_button, state.add_client_button, state.report_button):
            try:
                theme.register(btn)
            except Exception:
                logger.exception("Failed to register button with EDMC theme")

    frame.columnconfigure(text_col_start + 1, weight=1)
    return frame


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> tk.Frame:
    """Builds the settings tab in EDMC's preferences."""
    frame = nb.Frame(parent)

    state.api_base_var = tk.StringVar(value=state.api_base)
    state.api_key_var = tk.StringVar(value=state.api_key)
    state.show_api_key_var = tk.BooleanVar(value=False)
    state.overlay_master_var = tk.BooleanVar(value=_overlay_enabled["master"])
    state.overlay_scan_var = tk.BooleanVar(value=_overlay_enabled["scan"])
    state.overlay_newtarget_var = tk.BooleanVar(value=_overlay_enabled["newtarget"])
    state.overlay_plunder_var = tk.BooleanVar(value=_overlay_enabled["plunder"])
    state.overlay_client_var = tk.BooleanVar(value=_overlay_enabled["client"])

    # Header: logo + plugin name/version
    header = nb.Frame(frame)
    header.grid(row=0, column=0, columnspan=2, sticky="we", padx=8, pady=(8, 12))

    state.prefs_icon_image = _load_icon(64)
    if state.prefs_icon_image is not None:
        nb.Label(header, image=state.prefs_icon_image).grid(
            row=0, column=0, rowspan=2, sticky="w", padx=(0, 12)
        )

    nb.Label(header, text="Davy Jones Locker").grid(row=0, column=1, sticky="w")
    nb.Label(
        header, text=f"EDMC plugin v{PLUGIN_VERSION}"
    ).grid(row=1, column=1, sticky="w")

    nb.Label(frame, text="API base URL:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
    tk.Entry(frame, textvariable=state.api_base_var, width=40).grid(
        row=1, column=1, sticky="we", padx=8, pady=4
    )

    nb.Label(frame, text="API key:").grid(row=2, column=0, sticky="w", padx=8, pady=4)
    state.api_key_entry = tk.Entry(frame, textvariable=state.api_key_var, width=40, show="*")
    state.api_key_entry.grid(row=2, column=1, sticky="we", padx=8, pady=4)

    nb.Checkbutton(
        frame, text="Show API key",
        variable=state.show_api_key_var,
        command=_toggle_api_key_visibility,
    ).grid(row=3, column=1, sticky="w", padx=8, pady=(0, 4))

    nb.Label(
        frame,
        text="Get your API key from the Davy Jones Discord. Beta opt-in.",
    ).grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 16))

    # --- Overlay toggles ---
    nb.Label(frame, text="Overlay:").grid(
        row=5, column=0, sticky="nw", padx=8, pady=4
    )
    overlay_toggles = nb.Frame(frame)
    overlay_toggles.grid(row=5, column=1, sticky="w", padx=8, pady=4)
    nb.Checkbutton(
        overlay_toggles, text="Enable overlay (master)",
        variable=state.overlay_master_var,
    ).grid(row=0, column=0, sticky="w")
    nb.Checkbutton(
        overlay_toggles, text="Show scan results (known clients)",
        variable=state.overlay_scan_var,
    ).grid(row=1, column=0, sticky="w", padx=(20, 0))
    nb.Checkbutton(
        overlay_toggles, text="Show new-target scans (not in client list)",
        variable=state.overlay_newtarget_var,
    ).grid(row=2, column=0, sticky="w", padx=(20, 0))
    nb.Checkbutton(
        overlay_toggles, text="Show plunder confirmations",
        variable=state.overlay_plunder_var,
    ).grid(row=3, column=0, sticky="w", padx=(20, 0))
    nb.Checkbutton(
        overlay_toggles, text="Show client-add confirmations",
        variable=state.overlay_client_var,
    ).grid(row=4, column=0, sticky="w", padx=(20, 0))

    # --- HUD test section ---
    nb.Label(frame, text="Overlay test:").grid(
        row=6, column=0, sticky="nw", padx=8, pady=4
    )
    # Plain tk.Frame here — nb.Frame has its own internal grid layout and won't allow pack()
    test_buttons = tk.Frame(frame)
    test_buttons.grid(row=6, column=1, sticky="w", padx=8, pady=4)
    tk.Button(
        test_buttons, text="Test scan (known client)",
        command=_test_overlay_known,
    ).pack(side="left", padx=(0, 4))
    tk.Button(
        test_buttons, text="Test scan (cooldown)",
        command=_test_overlay_cooldown,
    ).pack(side="left", padx=4)
    tk.Button(
        test_buttons, text="Test scan (new target)",
        command=_test_overlay_newtarget,
    ).pack(side="left", padx=4)
    tk.Button(
        test_buttons, text="Test plunder toast",
        command=_test_overlay_toast,
    ).pack(side="left", padx=4)

    nb.Label(
        frame,
        text=(
            "Test buttons fire sample messages via EDMCModernOverlay (if installed) "
            "regardless of the per-event toggles above. Useful to verify position and styling."
        ),
        wraplength=480, justify="left",
    ).grid(row=7, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 8))

    frame.columnconfigure(1, weight=1)
    return frame


def _toggle_api_key_visibility() -> None:
    """Flip the API key entry between masked and plain."""
    if not state.api_key_entry or not state.show_api_key_var:
        return
    state.api_key_entry.config(show="" if state.show_api_key_var.get() else "*")


def _test_overlay_known() -> None:
    """Fire a sample 'known client' scan message via the overlay."""
    if not overlay.is_available():
        messagebox.showinfo(
            "DavyJones",
            "Overlay not detected. Install EDMCModernOverlay to use HUD messages."
        )
        return
    overlay.show_scan_result(
        "TEST CMDR", "KNOWN CLIENT",
        subtext="robbed 3x - last 8 days ago",
        color=overlay.COLOR_GREEN,
    )


def _test_overlay_cooldown() -> None:
    """Fire a sample 'on cooldown' scan message via the overlay."""
    if not overlay.is_available():
        messagebox.showinfo(
            "DavyJones",
            "Overlay not detected. Install EDMCModernOverlay to use HUD messages."
        )
        return
    overlay.show_scan_result(
        "TEST CMDR", "ON COOLDOWN",
        subtext="last robbed 2 hours ago",
        color=overlay.COLOR_RED,
    )


def _test_overlay_newtarget() -> None:
    """Fire a sample 'new target / not in client list' scan message via the overlay."""
    if not overlay.is_available():
        messagebox.showinfo(
            "DavyJones",
            "Overlay not detected. Install EDMCModernOverlay to use HUD messages."
        )
        return
    overlay.show_scan_result(
        "TEST CMDR", "NEW TARGET",
        subtext="not in client list",
        color=overlay.COLOR_BLUE,
    )


def _test_overlay_toast() -> None:
    """Fire a sample plunder confirmation toast via the overlay."""
    if not overlay.is_available():
        messagebox.showinfo(
            "DavyJones",
            "Overlay not detected. Install EDMCModernOverlay to use HUD messages."
        )
        return
    overlay.show_toast(
        "PLUNDER LOGGED",
        subtext="47t across 3 item(s) (PvP)",
        color=overlay.COLOR_GREEN,
    )


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
        ("newtarget", "overlay_newtarget_var"),
        ("plunder", "overlay_plunder_var"),
        ("client", "overlay_client_var"),
    ]:
        var = getattr(state, var_name, None)
        if var is not None:
            value = bool(var.get())
            _overlay_enabled[key] = value
            _set_bool_pref(f"davyjones_overlay_{key}", value)
    _set_status("Settings saved")


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
    """ShipTargeted fires multiple times as scan stages complete. For human commanders,
    PilotName / PilotName_Localised appear at ScanStage 2 — not 3 like for NPCs."""
    if not entry.get("TargetLocked"):
        return
    if entry.get("ScanStage", 0) < 2:
        return
    pilot_name = entry.get("PilotName") or ""
    if not pilot_name.startswith("$cmdr_decorate:#name="):
        # Only act on actual commanders, not NPCs. NPCs have names like
        # "$npc_name_decorate:#name=..." or "$ShipName_..." etc.
        return
    # Format is "$cmdr_decorate:#name=ROHAN DEX;" — strip the wrapper
    cmdr_name = pilot_name.replace("$cmdr_decorate:#name=", "").rstrip(";").strip()
    if not cmdr_name:
        return
    # Add to scan history: most recent first, dedup, cap at 50
    if cmdr_name in state.scan_history:
        state.scan_history.remove(cmdr_name)
    state.scan_history.insert(0, cmdr_name)
    state.scan_history = state.scan_history[:50]

    # Suppress repeated API lookups for the same CMDR within 30 seconds.
    # ShipTargeted fires at multiple scan stages; re-checking the same name is wasteful.
    now = time.monotonic()
    if state.last_lookup and state.last_lookup[0] == cmdr_name and (now - state.last_lookup[1]) < 30:
        return
    state.last_lookup = (cmdr_name, now)
    _lookup_client_async(cmdr_name)


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
            _set_scan(cmdr_name, "not in client list", color="gray")
            # Show on overlay only if user opted in — otherwise this fires on every scan
            if _overlay_on("newtarget"):
                overlay.show_scan_result(
                    cmdr_name, "NEW TARGET",
                    subtext="not in client list",
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
        _set_scan(cmdr_name, "not in client list", color="gray")
        return

    on_cooldown = bool(result.get("onCooldown"))
    last_robbed = _fmt_relative_time(result.get("lastRobbedAt"))
    times_robbed = result.get("timesRobbed", 0)

    if on_cooldown:
        msg = f"⛔ ON COOLDOWN — last robbed {last_robbed}"
        color = "red"
        overlay_header = "ON COOLDOWN"
        overlay_subtext = f"last robbed {last_robbed}"
        overlay_color = overlay.COLOR_RED
    else:
        msg = f"✓ client (robbed {times_robbed}×, last {last_robbed})"
        color = "green"
        overlay_header = "KNOWN CLIENT"
        overlay_subtext = f"robbed {times_robbed}x - last {last_robbed}"
        overlay_color = overlay.COLOR_GREEN
    _set_scan(cmdr_name, msg, color=color)
    if _overlay_on("scan"):
        overlay.show_scan_result(
            cmdr_name, overlay_header,
            subtext=overlay_subtext, color=overlay_color,
        )


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


# ---------------------------------------------------------------------------
# UI helpers (thread-safe via after())
# ---------------------------------------------------------------------------

def _set_status(text: str) -> None:
    if state.status_label:
        state.status_label.after(0, lambda: state.status_label.config(text=f"DavyJones: {text}"))


def _set_scan(cmdr_name: str, text: str, color: str = "black") -> None:
    if state.scan_label:
        state.scan_label.after(
            0,
            lambda: state.scan_label.config(text=f"{cmdr_name}: {text}", fg=color),
        )

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
        scan_history=list(state.scan_history),
        submit_callback=submit_add_client,
    )
