"""Overlay integration for EDMCModernOverlay (and backwards-compatible with legacy EDMCOverlay).

The overlay is OPTIONAL. If the user doesn't have it installed, every method here is a no-op.

EDMCModernOverlay registers itself as the `edmcoverlay` module to maintain API compatibility
with the original EDMCOverlay. We use two facilities:
  - `send_message(msgid, text, color, x, y, ttl, size)` for text
  - `send_shape(...)` for a thin vertical accent rule on the left of each block

Design (BGS-Tally inspired, glance-optimised for a combat HUD):
  - No filled background band. Each block instead carries a slim color-coded *accent rule*
    down its left edge — it codes the whole block's status without shouting.
  - The VERDICT leads (large, colored). The CMDR name is confirmation (white). Context is
    quiet grey underneath. The eye lands on red/green/amber first, then drills down.
  - Overlay text stays within Latin-1 (× · ) — the overlay font is not guaranteed to carry
    the dingbat glyphs (✓ ⚠) that the EDMC tk panel can use.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger("DavyJones.overlay")

# Coordinate layout — all our payloads stack vertically in one corner.
# The user can move the whole group via the EDMCModernOverlay Overlay Controller.
_X = 50            # left edge: where the accent rule sits
_Y_SCAN = 100      # CMDR scan block: accent + verdict start here
_Y_TOAST = 290     # Plunder/add-client toast: leaves room for the taller 3-line scan block
_ttl_scan = 6      # seconds — configurable via set_ttls()
_ttl_toast = 4     # seconds — configurable via set_ttls()

# Accent rule + text geometry.
_ACCENT_W = 3                       # accent rule width in overlay pixels
_ACCENT_GAP = 9                     # gap between the rule and the text
_TEXT_X = _X + _ACCENT_W + _ACCENT_GAP
_LINE_AFTER_TITLE = 30              # gap from a large title line down to the first line below it
_LINE_HEIGHT = 22                  # gap between subsequent lines
_LARGE_CAP = 24                    # approx rendered height of a "large" line (for accent sizing)
_NORMAL_CAP = 18                   # approx rendered height of a "normal" line

# Stable IDs so EDMCModernOverlay knows to REPLACE, not stack.
# Scan uses 4 IDs: accent rule + verdict + name + context. Toast uses 3: accent + title + sub.
_ID_SCAN_ACCENT = "davyjones_scan_accent"
_ID_SCAN_VERDICT = "davyjones_scan_verdict"
_ID_SCAN_NAME = "davyjones_scan_name"
_ID_SCAN_DETAIL = "davyjones_scan_detail"
_ID_TOAST_ACCENT = "davyjones_toast_accent"
_ID_TOAST_TEXT = "davyjones_toast_text"
_ID_TOAST_SUB = "davyjones_toast_sub"

# Color palette — saturated for visibility in-game against a dark space backdrop.
# Semantics (kept deliberately tight so they're learnable at a glance):
#   RED   = threat / failure      (combat logger, errors)
#   AMBER = blocked / wait        (cooldown, already-in-list)
#   GREEN = good outcome          (known client, logged)
#   BLUE  = neutral / new         (new target)
COLOR_GREEN = "#1ea84a"
COLOR_RED = "#cc1f3a"
COLOR_BLUE = "#1f7ad2"
COLOR_AMBER = "#e6a800"
COLOR_WHITE = "#ffffff"
COLOR_GREY = "#9aa0a6"     # dim subordinate detail text


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
        """Draw a filled rect via send_shape (used for the thin left accent rule).
        Some overlay implementations expose send_shape, others only send_raw — try the
        common path first, fall back to the legacy EDMCOverlay JSON form."""
        if not self._ensure_loaded():
            return
        with self._lock:
            try:
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


def set_ttls(scan: int, toast: int) -> None:
    global _ttl_scan, _ttl_toast
    _ttl_scan = max(1, scan)
    _ttl_toast = max(1, toast)


def show_scan_result(cmdr_name: str, state: str, subtext: str = "",
                     color: str = COLOR_GREEN) -> None:
    """Display a CMDR scan result as a color-coded card (BGS-Tally inspired):

        ▍ KNOWN CLIENT              <- verdict: large, in the status color (lead with the decision)
        ▍ CMDR Hadfield            <- who: white, confirmation
        ▍ robbed 3× · last 8d ago  <- why: dim grey context

    `state` is the verdict and drives both the colored header and the accent rule. `cmdr_name`
    is rendered as a quiet confirmation line beneath it, and `subtext` is the grey context."""
    verdict = (state or "?").upper()
    name = (cmdr_name or "?").strip()

    # Accent rule spans the whole block: verdict (large) + name + optional context line.
    last_offset = _LINE_AFTER_TITLE + (_LINE_HEIGHT if subtext else 0)
    block_h = last_offset + _NORMAL_CAP
    _wrapper._send_rect(
        _ID_SCAN_ACCENT, _X, _Y_SCAN, _ACCENT_W, block_h, fill=color, ttl=_ttl_scan,
    )
    _wrapper._send_text(
        _ID_SCAN_VERDICT, verdict, color,
        _TEXT_X, _Y_SCAN,
        ttl=_ttl_scan, size="large",
    )
    _wrapper._send_text(
        _ID_SCAN_NAME, f"CMDR {name}", COLOR_WHITE,
        _TEXT_X, _Y_SCAN + _LINE_AFTER_TITLE,
        ttl=_ttl_scan, size="normal",
    )
    if subtext:
        _wrapper._send_text(
            _ID_SCAN_DETAIL, subtext, COLOR_GREY,
            _TEXT_X, _Y_SCAN + _LINE_AFTER_TITLE + _LINE_HEIGHT,
            ttl=_ttl_scan, size="normal",
        )


def show_toast(header: str, subtext: str = "",
               color: str = COLOR_GREEN, ttl: int = -1) -> None:
    """Brief notification — plunder/add-client confirmations and errors.
    Same card language as the scan block but lighter: colored title + dim grey subtext.
    The title here is already an action verb ('PLUNDER LOGGED'), so no separate verdict."""
    effective_ttl = _ttl_toast if ttl < 0 else ttl
    title = (header or "").upper()

    last_offset = _LINE_AFTER_TITLE if subtext else 0
    block_h = last_offset + (_NORMAL_CAP if subtext else _LARGE_CAP)
    _wrapper._send_rect(
        _ID_TOAST_ACCENT, _X, _Y_TOAST, _ACCENT_W, block_h, fill=color, ttl=effective_ttl,
    )
    _wrapper._send_text(
        _ID_TOAST_TEXT, title, color,
        _TEXT_X, _Y_TOAST,
        ttl=effective_ttl, size="large",
    )
    if subtext:
        _wrapper._send_text(
            _ID_TOAST_SUB, subtext, COLOR_GREY,
            _TEXT_X, _Y_TOAST + _LINE_AFTER_TITLE,
            ttl=effective_ttl, size="normal",
        )
