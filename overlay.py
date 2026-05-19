"""Overlay integration for EDMCModernOverlay (and backwards-compatible with legacy EDMCOverlay).

The overlay is OPTIONAL. If the user doesn't have it installed, every method here is a no-op.

EDMCModernOverlay registers itself as the `edmcoverlay` module to maintain API compatibility
with the original EDMCOverlay. We use two facilities:
  - `send_message(msgid, text, color, x, y, ttl, size)` for text
  - `send_shape(...)` for filled rectangles (the colored header band)

For BGS-Tally-style "block header" messages we draw a filled rect first, then put white text
on top — two overlay IDs per message (one for the bar, one for the text), with the same TTL.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger("DavyJones.overlay")

# Coordinate layout — all our payloads stack vertically in one corner.
# The user can move the whole group via the EDMCModernOverlay Overlay Controller.
_X = 50
_Y_SCAN = 100      # CMDR scan: header bar starts here
_Y_TOAST = 290     # Plunder/add-client toast: leaves room for taller scan block (bar + 2 lines)
_TTL_SCAN = 6      # seconds
_TTL_TOAST = 4     # seconds

# Layout constants for the block header.
# `size="large"` text needs more vertical room than I first allowed — the descender was clipping
# the bottom of the box. The bar is taller now and the text Y offset re-centers within it.
_BAR_W = 360       # bar width in overlay pixels
_BAR_H = 36        # bar height (room for one "large" line with descenders + breathing room)
_TEXT_PAD_X = 10   # text indent inside the bar
_TEXT_PAD_Y = 6    # text offset down from the top of the bar (centers a "large" line)
_SUBTEXT_Y_OFFSET = _BAR_H + 6  # where the line under the bar starts
_STATE_Y_OFFSET = _BAR_H + 6    # state line directly under the bar (scan only)
_DETAIL_Y_OFFSET = _BAR_H + 26  # detail line below the state (scan only)

# Stable IDs so EDMCModernOverlay knows to REPLACE, not stack.
# Scan uses 4 IDs: bar + name + state + detail. Toast uses 3: bar + title + subtext.
_ID_SCAN_BAR = "davyjones_scan_bar"
_ID_SCAN_NAME = "davyjones_scan_name"
_ID_SCAN_STATE = "davyjones_scan_state"
_ID_SCAN_DETAIL = "davyjones_scan_detail"
_ID_TOAST_BAR = "davyjones_toast_bar"
_ID_TOAST_TEXT = "davyjones_toast_text"
_ID_TOAST_SUB = "davyjones_toast_sub"

# Color palette — saturated for visibility in-game against a dark space backdrop
COLOR_GREEN = "#1ea84a"    # success / known client
COLOR_RED = "#cc1f3a"      # warning / cooldown / failure
COLOR_BLUE = "#1f7ad2"     # neutral info
COLOR_AMBER = "#e6a800"    # duplicate / already-in-list
COLOR_WHITE = "#ffffff"


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

    def _send_rect(self, msg_id: str, x: int, y: int, w: int, h: int,
                   fill: str, ttl: int) -> None:
        """Draw a filled rect via send_shape. Some overlay implementations expose
        send_shape, others only send_raw — we try the most common path first."""
        if not self._ensure_loaded():
            return
        with self._lock:
            try:
                # The standard send_shape signature varies, but EDMCModernOverlay and
                # edmcoverlay2 both accept this kwargs form. EDMCOverlay (legacy) takes
                # JSON via send_raw — fall back to that if shape isn't available.
                send_shape = getattr(self._overlay, "send_shape", None)
                if callable(send_shape):
                    send_shape(
                        shapeid=msg_id, shape="rect",
                        color=fill, fill=fill,
                        x=x, y=y, w=w, h=h, ttl=ttl,
                    )
                    return
                send_raw = getattr(self._overlay, "send_raw", None)
                if callable(send_raw):
                    send_raw({
                        "id": msg_id, "shape": "rect",
                        "color": fill, "fill": fill,
                        "x": x, "y": y, "w": w, "h": h, "ttl": ttl,
                    })
            except Exception:
                logger.exception("Overlay send_shape/send_raw failed")


_wrapper = _OverlayWrapper()


def is_available() -> bool:
    return _wrapper.is_available()


def show_scan_result(cmdr_name: str, state: str, subtext: str = "",
                     color: str = COLOR_GREEN) -> None:
    """Display a CMDR scan result as a 3-line block:
      [colored bar with CMDR NAME in white, large]
      STATE in the bar's color, on its own line          (e.g. "KNOWN CLIENT")
      subtext in dim grey, below                         (e.g. "robbed 3x - last 8 days ago")
    The CMDR name gets the full bar to itself so it's the first thing the eye lands on."""
    name = (cmdr_name or "?").upper()
    _wrapper._send_rect(
        _ID_SCAN_BAR, _X, _Y_SCAN, _BAR_W, _BAR_H, fill=color, ttl=_TTL_SCAN,
    )
    _wrapper._send_text(
        _ID_SCAN_NAME, name, COLOR_WHITE,
        _X + _TEXT_PAD_X, _Y_SCAN + _TEXT_PAD_Y,
        ttl=_TTL_SCAN, size="large",
    )
    if state:
        _wrapper._send_text(
            _ID_SCAN_STATE, state, color,
            _X + _TEXT_PAD_X, _Y_SCAN + _STATE_Y_OFFSET,
            ttl=_TTL_SCAN, size="normal",
        )
    if subtext:
        _wrapper._send_text(
            _ID_SCAN_DETAIL, subtext, COLOR_WHITE,
            _X + _TEXT_PAD_X, _Y_SCAN + _DETAIL_Y_OFFSET,
            ttl=_TTL_SCAN, size="normal",
        )


def show_toast(header: str, subtext: str = "",
               color: str = COLOR_GREEN, ttl: int = _TTL_TOAST) -> None:
    """Brief notification — used for plunder/add-client confirmations and errors.
    Two-line layout: bar with title, dim subtext below. Simpler than scan because the title
    here is already an action verb ('PLUNDER LOGGED'), no separate state needed."""
    _wrapper._send_rect(
        _ID_TOAST_BAR, _X, _Y_TOAST, _BAR_W, _BAR_H, fill=color, ttl=ttl,
    )
    _wrapper._send_text(
        _ID_TOAST_TEXT, header, COLOR_WHITE,
        _X + _TEXT_PAD_X, _Y_TOAST + _TEXT_PAD_Y,
        ttl=ttl, size="large",
    )
    if subtext:
        _wrapper._send_text(
            _ID_TOAST_SUB, subtext, color,
            _X + _TEXT_PAD_X, _Y_TOAST + _SUBTEXT_Y_OFFSET,
            ttl=ttl, size="normal",
        )
