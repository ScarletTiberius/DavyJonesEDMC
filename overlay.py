"""Overlay integration for EDMCModernOverlay (and backwards-compatible with legacy EDMCOverlay).

The overlay is OPTIONAL. If the user doesn't have it installed, every method here is a no-op.

EDMCModernOverlay registers itself as the `edmcoverlay` module to maintain API compatibility
with the original EDMCOverlay. We use one facility:
  - `send_message(msgid, text, color, x, y, ttl, size)` for text

For BGS-Tally-style messages we draw a colored text title/header (no filled background band),
with subordinate lines stacked underneath. Each line is its own overlay ID with the same TTL.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger("DavyJones.overlay")

# Coordinate layout — all our payloads stack vertically in one corner.
# The user can move the whole group via the EDMCModernOverlay Overlay Controller.
_X = 50
_Y_SCAN = 100      # CMDR scan: colored title starts here
_Y_TOAST = 290     # Plunder/add-client toast: leaves room for taller scan block (3 lines)
_ttl_scan = 6      # seconds — configurable via set_ttls()
_ttl_toast = 4     # seconds — configurable via set_ttls()

# Line layout — no header bar, just stacked text lines (BGS-Tally style).
# A "large" title line needs more vertical room than a "normal" line.
_LINE_AFTER_TITLE = 30  # gap from a large title line down to the first line below it
_LINE_HEIGHT = 20       # gap between subsequent normal lines
_STATE_Y_OFFSET = _LINE_AFTER_TITLE                    # state line under the title (scan only)
_DETAIL_Y_OFFSET = _LINE_AFTER_TITLE + _LINE_HEIGHT    # detail line below the state (scan only)
_SUBTEXT_Y_OFFSET = _LINE_AFTER_TITLE                  # subtext under the title (toast)

# Stable IDs so EDMCModernOverlay knows to REPLACE, not stack.
# Scan uses 3 IDs: name + state + detail. Toast uses 2: title + subtext.
_ID_SCAN_NAME = "davyjones_scan_name"
_ID_SCAN_STATE = "davyjones_scan_state"
_ID_SCAN_DETAIL = "davyjones_scan_detail"
_ID_TOAST_TEXT = "davyjones_toast_text"
_ID_TOAST_SUB = "davyjones_toast_sub"

# Color palette — saturated for visibility in-game against a dark space backdrop
COLOR_GREEN = "#1ea84a"    # success / known client
COLOR_RED = "#cc1f3a"      # warning / cooldown / failure
COLOR_BLUE = "#1f7ad2"     # neutral info
COLOR_AMBER = "#e6a800"    # duplicate / already-in-list
COLOR_WHITE = "#ffffff"
COLOR_GREY = "#b0b0b0"     # dim subordinate detail text


class _OverlayWrapper:
    """Wraps the optional edmcoverlay module. Safe to call methods even if overlay isn't available."""

    def __init__(self) -> None:
        self._overlay = None
        self._available = False
        self._tried_import = False
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        if self._tried_import:
            return self._available
        self._tried_import = True
        try:
            import edmcoverlay  # type: ignore
            self._overlay = edmcoverlay.Overlay()
            self._available = True
            logger.info("Overlay detected and initialised")
        except ImportError:
            logger.info("Overlay not installed — HUD messages disabled")
        except Exception:
            logger.exception("Overlay initialisation failed — HUD messages disabled")
        return self._available

    def is_available(self) -> bool:
        return self._ensure_loaded()

    def _send_text(self, msg_id: str, text: str, color: str, x: int, y: int,
                   ttl: int, size: str = "normal") -> None:
        if not self._ensure_loaded():
            return
        with self._lock:
            try:
                self._overlay.send_message(msg_id, text, color, x, y, ttl=ttl, size=size)
            except Exception:
                logger.exception("Overlay send_message failed")


_wrapper = _OverlayWrapper()


def is_available() -> bool:
    return _wrapper.is_available()


def set_ttls(scan: int, toast: int) -> None:
    global _ttl_scan, _ttl_toast
    _ttl_scan = max(1, scan)
    _ttl_toast = max(1, toast)


def show_scan_result(cmdr_name: str, state: str, subtext: str = "",
                     color: str = COLOR_GREEN) -> None:
    """Display a CMDR scan result as a 3-line block (BGS-Tally style):
      CMDR NAME in the state color, large                  (the colored title/header)
      STATE in the same color, on its own line             (e.g. "KNOWN CLIENT")
      subtext in dim grey, below                           (e.g. "robbed 3x - last 8 days ago")
    The CMDR name is the colored header so it's the first thing the eye lands on."""
    name = (cmdr_name or "?").upper()
    _wrapper._send_text(
        _ID_SCAN_NAME, name, color,
        _X, _Y_SCAN,
        ttl=_ttl_scan, size="large",
    )
    if state:
        _wrapper._send_text(
            _ID_SCAN_STATE, state, color,
            _X, _Y_SCAN + _STATE_Y_OFFSET,
            ttl=_ttl_scan, size="normal",
        )
    if subtext:
        _wrapper._send_text(
            _ID_SCAN_DETAIL, subtext, COLOR_GREY,
            _X, _Y_SCAN + _DETAIL_Y_OFFSET,
            ttl=_ttl_scan, size="normal",
        )


def show_toast(header: str, subtext: str = "",
               color: str = COLOR_GREEN, ttl: int = -1) -> None:
    """Brief notification — used for plunder/add-client confirmations and errors.
    Two-line layout (BGS-Tally style): colored title header, dim subtext below. The title
    here is already an action verb ('PLUNDER LOGGED'), no separate state needed."""
    effective_ttl = _ttl_toast if ttl < 0 else ttl
    _wrapper._send_text(
        _ID_TOAST_TEXT, header, color,
        _X, _Y_TOAST,
        ttl=effective_ttl, size="large",
    )
    if subtext:
        _wrapper._send_text(
            _ID_TOAST_SUB, subtext, COLOR_GREY,
            _X, _Y_TOAST + _SUBTEXT_Y_OFFSET,
            ttl=effective_ttl, size="normal",
        )
