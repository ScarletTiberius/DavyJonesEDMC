"""Shared visual language for DavyJones popup windows.

All widget factories use plain `tk` widgets — no `ttk` — because `ttk.Style().theme_use()` is
PROCESS-WIDE and changing it would re-render every other plugin's ttk widgets. Plain tk widgets
fully respect color attributes, so we get our dark aesthetic without affecting EDMC or BGS-Tally.

The hacker-pirate-codex aesthetic: pitch black, blood red headers, cyan/amber/pink/green data.
"""

import sys
import tkinter as tk
from typing import Callable, List, Optional


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------
# Every color used anywhere in the plugin is read from the live `PALETTE` dict
# below, at the moment a widget is built. To switch themes we don't touch any
# widget code — we just swap PALETTE's *contents* (clear + update, see
# `apply_theme`) so the dict object stays identical and every existing reference,
# including `t.PALETTE[...]` lookups in the window modules, keeps working.
#
# The semantic keys (accent_red, accent_cyan, accent_green, accent_pink, ...)
# carry meaning beyond their literal color name: accent_red is the primary/header
# accent, accent_green = PvE/success, accent_pink = PvP, accent_cyan = data.
# Each theme remaps those slots to colors that fit its mood — so "accent_red"
# in Imperial Gold is gold, in Classic Amber is orange, etc.

THEMES: dict = {
    # The original hacker-pirate-codex aesthetic: pitch black, blood red headers.
    "davy_jones": {
        "bg":            "#0a0a0a",   # near-black main bg
        "bg_alt":        "#141414",   # alternating rows / subtle elevation
        "bg_card":       "#0f0f10",   # cards slightly different from bg
        "bg_input":      "#1a1520",   # entry/spinbox bg — dark purple-tinted
        "fg":            "#d8d8d8",   # body text — off-white
        "fg_dim":        "#5a5a5a",   # labels / metadata
        "accent_red":    "#c8102e",   # blood red — headers, dividers, primary accents
        "accent_red_dim": "#5a0f1a",  # darker red for borders
        "accent_cyan":   "#5fd7ff",   # primary data — tonnage, counts
        "accent_amber":  "#ffb347",   # credits / value
        "accent_green":  "#4eff8c",   # PvE / success
        "accent_pink":   "#ff5577",   # PvP
        "border":        "#4a1020",   # dark red border — visible against bg_input
        "border_hot":    "#c8102e",   # emphasised border
    },
    # Empire-flavoured: warm near-black bg, gold/cream accents.
    "imperial_gold": {
        "bg":            "#0d0b06",
        "bg_alt":        "#161109",
        "bg_card":       "#12100a",
        "bg_input":      "#1c1710",
        "fg":            "#e8dcc0",   # cream body text
        "fg_dim":        "#6b6048",
        "accent_red":    "#d4af37",   # gold — headers / primary accent
        "accent_red_dim": "#5a4a18",  # dark gold for borders
        "accent_cyan":   "#f0d98a",   # light gold — data
        "accent_amber":  "#ffcf6b",   # bright amber — credits
        "accent_green":  "#b5c46b",   # olive — PvE / success
        "accent_pink":   "#d98a5a",   # copper — PvP
        "border":        "#4a3a14",
        "border_hot":    "#d4af37",
    },
    # Old amber CRT terminal: black bg, amber monochrome with a phosphor-green pop.
    "classic_amber": {
        "bg":            "#0a0700",
        "bg_alt":        "#120d00",
        "bg_card":       "#0e0a00",
        "bg_input":      "#161000",
        "fg":            "#ffb000",   # amber text
        "fg_dim":        "#7a5500",
        "accent_red":    "#ff7a00",   # orange-amber — headers
        "accent_red_dim": "#5a2a00",
        "accent_cyan":   "#ffcc00",   # bright amber — data
        "accent_amber":  "#ffb000",
        "accent_green":  "#88ff00",   # phosphor green — PvE / success
        "accent_pink":   "#ff5500",   # red-orange — PvP
        "border":        "#4a3300",
        "border_hot":    "#ff7a00",
    },
    # Elite Dangerous / EDMC native look: pure-black cockpit bg, signature ED
    # HUD orange (#ff7100) accents, warm off-white body text.
    "elite_orange": {
        "bg":            "#000000",
        "bg_alt":        "#0e0e0e",
        "bg_card":       "#0a0a0a",
        "bg_input":      "#1a1408",
        "fg":            "#ffb070",   # warm light-orange body text
        "fg_dim":        "#875a2a",
        "accent_red":    "#ff7100",   # ED HUD orange — headers / primary accent
        "accent_red_dim": "#5a2a00",
        "accent_cyan":   "#ff9d45",   # lighter orange — data
        "accent_amber":  "#ffb000",   # amber — credits
        "accent_green":  "#7fd44f",   # friendly green — PvE / success
        "accent_pink":   "#ff4422",   # hostile red — PvP
        "border":        "#4a3000",
        "border_hot":    "#ff7100",
    },
    # Neutral dark grey — no special colors. Muted green/red kept only so the
    # PvE/PvP segmented controls remain distinguishable.
    "plain": {
        "bg":            "#1e1e1e",
        "bg_alt":        "#252525",
        "bg_card":       "#232323",
        "bg_input":      "#2a2a2a",
        "fg":            "#e0e0e0",
        "fg_dim":        "#808080",
        "accent_red":    "#cfcfcf",   # neutral light grey — headers / accent
        "accent_red_dim": "#444444",
        "accent_cyan":   "#d6d6d6",   # data
        "accent_amber":  "#d6d6d6",   # credits
        "accent_green":  "#9ec79e",   # muted green — PvE / success
        "accent_pink":   "#c79e9e",   # muted red — PvP
        "border":        "#3a3a3a",
        "border_hot":    "#8a8a8a",
    },
}

# "native" — the no-theming look used when the user unchecks "Enable custom
# theme". It maps the slots to the OS's own widget colors so the windows follow
# the standard Windows light/dark theme (light-grey chrome, white input fields,
# black text, blue selection highlight). On Windows we use Tk's documented
# `System*` color names; on other platforms those names may not resolve and
# would raise at widget creation, so we fall back to neutral light literals.
# green/red are kept for the PvE/PvP and success/danger semantics — they read as
# normal status colors in a native app and the labels would be ambiguous without.
#
# Note this only swaps colors: the widgets keep their flat relief and monospace
# font (those aren't palette-driven), so it's "native colors", not native chrome.
if sys.platform == "win32":
    THEMES["native"] = {
        "bg":            "SystemButtonFace",   # standard dialog grey
        "bg_alt":        "SystemButtonFace",
        "bg_card":       "SystemButtonFace",
        "bg_input":      "SystemWindow",       # white input background
        "fg":            "SystemWindowText",   # black body text
        "fg_dim":        "SystemGrayText",     # greyed/disabled text
        "accent_red":    "SystemHighlight",    # OS selection accent (headers/primary)
        "accent_red_dim": "SystemButtonShadow",
        "accent_cyan":   "SystemWindowText",   # data → plain text
        "accent_amber":  "SystemWindowText",   # credits → plain text
        "accent_green":  "#107c10",            # success / PvE
        "accent_pink":   "#c50f1f",            # danger / PvP
        "border":        "SystemButtonShadow",
        "border_hot":    "SystemHighlight",
    }
else:
    THEMES["native"] = {
        "bg":            "#f0f0f0",
        "bg_alt":        "#f0f0f0",
        "bg_card":       "#f0f0f0",
        "bg_input":      "#ffffff",
        "fg":            "#000000",
        "fg_dim":        "#6d6d6d",
        "accent_red":    "#0078d4",
        "accent_red_dim": "#a0a0a0",
        "accent_cyan":   "#000000",
        "accent_amber":  "#000000",
        "accent_green":  "#107c10",
        "accent_pink":   "#c50f1f",
        "border":        "#a0a0a0",
        "border_hot":    "#0078d4",
    }

# Ordered (key, human label) pairs — drives the settings dropdown and the
# default. "native" is intentionally NOT listed: it's not a "theme" you pick,
# it's the no-theming fallback the disable checkbox applies. Keep "davy_jones"
# first; it's the default.
THEME_ORDER = [
    ("davy_jones",    "Davy Jones"),
    ("imperial_gold", "Imperial Gold"),
    ("classic_amber", "Classic Amber"),
    ("elite_orange",  "Elite Orange"),
    ("plain",         "Plain"),
]
DEFAULT_THEME = "davy_jones"

# Live palette. Starts as the default; `apply_theme` mutates it in place so all
# references (here and in the window modules) follow without reassignment.
PALETTE: dict = dict(THEMES[DEFAULT_THEME])
_active_theme = DEFAULT_THEME


def apply_theme(name: str) -> None:
    """Switch the active palette to theme `name` (a THEMES key). Unknown names
    fall back to the default. Mutates PALETTE in place so existing references
    stay valid; already-open windows aren't repainted — the change takes effect
    the next time a window is built."""
    global _active_theme
    theme = THEMES.get(name) or THEMES[DEFAULT_THEME]
    _active_theme = name if name in THEMES else DEFAULT_THEME
    PALETTE.clear()
    PALETTE.update(theme)


def active_theme() -> str:
    """The key of the currently applied theme."""
    return _active_theme


def label_for(key: str) -> str:
    """Human label for a theme key (key itself if unknown)."""
    for k, lbl in THEME_ORDER:
        if k == key:
            return lbl
    return key


def key_for(label: str) -> str:
    """Theme key for a human label (DEFAULT_THEME if unknown)."""
    for k, lbl in THEME_ORDER:
        if lbl == label:
            return k
    return DEFAULT_THEME

FONT_HEADER = ("Consolas", 11, "bold")
FONT_BIG    = ("Consolas", 13, "bold")
FONT_BODY   = ("Consolas", 10)
FONT_LABEL  = ("Consolas", 8)
FONT_BADGE  = ("Consolas", 8, "bold")
FONT_TITLE  = ("Consolas", 14, "bold")

# Session-only geometry cache, keyed by a window identifier string.
# Survives close-and-reopen within an EDMC session; wiped on EDMC restart (intentional —
# screen layouts can change between sessions, fresh-positioning is the safer default).
_remembered_geometry: dict = {}

def restore_or_position(window: tk.Toplevel, key: str, offset: int = 60) -> None:
    """Open the window where it was last closed (this session). On first open,
    position it near the parent. Call after the initial geometry("WxH") so
    only x/y is overridden, not size."""
    saved = _remembered_geometry.get(key)
    if saved:
        try:
            window.geometry(saved)
            return
        except Exception:
            pass
    position_near_parent(window, offset)

def remember_geometry(window: tk.Toplevel, key: str) -> None:
    """Call from the window's destroy handler (or bind <Destroy>) to capture
    where the user last had it."""
    try:
        _remembered_geometry[key] = window.geometry()
    except Exception:
        pass    

# ---------------------------------------------------------------------------
# Widget factories — pure tk, every widget styled at creation
# ---------------------------------------------------------------------------

def frame(parent: tk.Misc, bg: Optional[str] = None, **kw) -> tk.Frame:
    return tk.Frame(parent, bg=bg or PALETTE["bg"], **kw)


def label(
    parent: tk.Misc,
    text: str = "",
    fg: Optional[str] = None,
    bg: Optional[str] = None,
    font=FONT_BODY,
    **kw,
) -> tk.Label:
    return tk.Label(
        parent, text=text,
        fg=fg or PALETTE["fg"], bg=bg or PALETTE["bg"],
        font=font, **kw,
    )


def button(
    parent: tk.Misc,
    text: str,
    command: Callable,
    accent: Optional[str] = None,
    **kw,
) -> tk.Button:
    """A button with an outline in `accent` color (default: blood red).
    Fills with the accent color on hover/click."""
    accent_color = accent or PALETTE["accent_red"]
    return tk.Button(
        parent, text=text, command=command,
        bg=PALETTE["bg_card"], fg=accent_color,
        activebackground=accent_color, activeforeground=PALETTE["bg"],
        relief=tk.FLAT, borderwidth=0,
        font=FONT_HEADER, padx=14, pady=4,
        highlightthickness=1,
        highlightbackground=accent_color,
        highlightcolor=accent_color,
        cursor="hand2",
        **kw,
    )


def entry(parent: tk.Misc, **kw) -> tk.Entry:
    return tk.Entry(
        parent,
        bg=PALETTE["bg_input"], fg=PALETTE["fg"],
        insertbackground=PALETTE["accent_red"],
        disabledbackground=PALETTE["bg_input"],
        disabledforeground=PALETTE["fg_dim"],
        relief=tk.FLAT, borderwidth=0,
        highlightthickness=1,
        highlightbackground=PALETTE["border"],
        highlightcolor=PALETTE["accent_red"],
        font=FONT_BODY,
        **kw,
    )


def spinbox(parent: tk.Misc, **kw) -> tk.Spinbox:
    return tk.Spinbox(
        parent,
        bg=PALETTE["bg_input"], fg=PALETTE["accent_cyan"],
        insertbackground=PALETTE["accent_red"],
        buttonbackground=PALETTE["bg_card"],
        relief=tk.FLAT, borderwidth=0,
        highlightthickness=1,
        highlightbackground=PALETTE["border"],
        highlightcolor=PALETTE["accent_red"],
        font=FONT_BODY,
        **kw,
    )


def option_menu(parent: tk.Misc, var: tk.StringVar, values: List[str]) -> tk.OptionMenu:
    """Drop-in replacement for ttk.Combobox(state='readonly'). OptionMenu fully respects
    tk color attributes — no global theme switch required."""
    menu = tk.OptionMenu(parent, var, *values)
    menu.configure(
        bg=PALETTE["bg_input"], fg=PALETTE["accent_cyan"],
        activebackground=PALETTE["accent_red"], activeforeground=PALETTE["bg"],
        relief=tk.FLAT, borderwidth=0,
        highlightthickness=1,
        highlightbackground=PALETTE["border"],
        highlightcolor=PALETTE["accent_red"],
        font=FONT_BODY,
        indicatoron=False,  # remove the default 3D arrow; cleaner look
        padx=10, pady=4,
        anchor="w",
    )
    # Style the dropdown itself too
    menu["menu"].configure(
        bg=PALETTE["bg_card"], fg=PALETTE["fg"],
        activebackground=PALETTE["accent_red"], activeforeground=PALETTE["bg"],
        relief=tk.FLAT, borderwidth=0,
        font=FONT_BODY,
    )
    return menu


def scrollbar(parent: tk.Misc, command: Callable) -> tk.Scrollbar:
    """Plain tk.Scrollbar. Classic 3D look but respects troughcolor and background.
    Less pretty than a custom-drawn scrollbar but has zero global impact."""
    return tk.Scrollbar(
        parent, orient="vertical", command=command,
        bg=PALETTE["bg_card"],
        troughcolor=PALETTE["bg"],
        activebackground=PALETTE["accent_red_dim"],
        relief=tk.FLAT,
        borderwidth=0,
        highlightthickness=0,
        width=12,
    )


class SegmentedRadio(tk.Frame):
    """Segmented-button-style radio group. Each option is a clickable button sitting in a row;
    the selected option fills with the accent color, others stay dim with an outline.

    Usage:
        radio = SegmentedRadio(parent, var, [
            ("PvE", "PvE", "#4eff8c"),  # (value, label, accent_color)
            ("PvP", "PvP", "#ff5577"),
        ])
        radio.pack(...)

    The `var` is a tk.StringVar; reading var.get() gives the currently selected value.
    """

    def __init__(
        self,
        parent: tk.Misc,
        var: tk.StringVar,
        options: List[tuple],  # list of (value, label, accent_color)
        **kw,
    ):
        # Force a minimum height so the frame can't collapse to zero even if the children
        # somehow fail to register their size requests
        super().__init__(parent, bg=PALETTE["bg"], height=40, **kw)
        # Don't let the children shrink us below `height=40` — propagate=False means
        # geometry of children doesn't dictate our size
        self.pack_propagate(False)
        self.grid_propagate(False)

        self._var = var
        self._option_specs = options  # NOT self._options — that shadows a Tk internal method
        self._buttons: List[tk.Button] = []

        for col, (value, lbl, color) in enumerate(options):
            btn = tk.Button(
                self,
                text=lbl,
                font=FONT_HEADER,
                command=lambda v=value: self._on_click(v),
                cursor="hand2",
                relief=tk.SOLID,            # SOLID renders a visible border on Windows
                borderwidth=2,
                padx=20, pady=8,
                bg=PALETTE["bg_card"],
                fg=color,
                activebackground=color,
                activeforeground=PALETTE["bg"],
            )
            btn.grid(
                row=0, column=col, sticky="nsew",
                padx=(0, 6) if col < len(options) - 1 else 0,
            )
            self._buttons.append(btn)
            self.columnconfigure(col, weight=1)
        self.rowconfigure(0, weight=1)

        # Repaint when var changes (e.g. programmatic .set())
        try:
            self._var.trace_add("write", lambda *a: self._refresh())
        except AttributeError:
            # Very old tkinter — fall back to legacy trace
            self._var.trace("w", lambda *a: self._refresh())  # type: ignore
        self._refresh()

    def _on_click(self, value: str) -> None:
        self._var.set(value)

    def _refresh(self) -> None:
        current = self._var.get()
        for (value, lbl, color), btn in zip(self._option_specs, self._buttons):
            if value == current:
                # Selected: fill with the accent color, bg-colored text
                btn.configure(bg=color, fg=PALETTE["bg"])
            else:
                # Unselected: dark bg, accent-colored text
                btn.configure(bg=PALETTE["bg_card"], fg=color)


def divider(parent: tk.Misc, color: Optional[str] = None, height: int = 1) -> tk.Frame:
    return tk.Frame(parent, bg=color or PALETTE["accent_red_dim"], height=height)


def position_near_parent(window: tk.Toplevel, offset: int = 60) -> None:
    """Place a Toplevel just below-right of its parent (EDMC's main window), so it always
    opens on whatever monitor EDMC is on. Call AFTER `geometry("WxH")` so the offset wins.

    tk's default behaviour is to center new Toplevels on the primary screen, which is wrong
    when EDMC lives on a secondary monitor. winfo_rootx/y are absolute screen coordinates
    across the whole virtual desktop, so they cross monitors correctly."""
    try:
        parent = window.master
        # winfo_rootx/y aren't reliable until the parent has been mapped; force an update
        parent.update_idletasks()
        x = parent.winfo_rootx() + offset
        y = parent.winfo_rooty() + offset
        # Keep the size that was already set, only adjust position
        window.geometry(f"+{x}+{y}")
    except Exception:
        # Positioning is a nicety; if winfo_root* fails (parent not mapped, etc.) skip silently
        pass


def title_bar(parent: tk.Misc, icon: str, title: str, subtitle: str = "") -> tk.Frame:
    """A standard window title: icon + UPPERCASE title // dim subtitle."""
    bar = frame(parent)
    bar.pack(fill="x", pady=(0, 4))
    label(
        bar, text=f"{icon}  {title}",
        fg=PALETTE["accent_red"], font=FONT_TITLE,
    ).pack(side="left")
    if subtitle:
        label(
            bar, text=f"  //  {subtitle.upper()}",
            fg=PALETTE["fg_dim"], font=FONT_HEADER,
        ).pack(side="left")
    return bar


def make_scrollable(parent: tk.Misc) -> tk.Frame:
    """Build a scrollable area, return the inner frame to pack content into."""
    wrap = frame(parent)
    wrap.pack(fill="both", expand=True)

    canvas = tk.Canvas(
        wrap, highlightthickness=0, bg=PALETTE["bg"], bd=0,
    )
    bar = scrollbar(wrap, command=canvas.yview)
    inner = frame(canvas)
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_configure(event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(window_id, width=canvas.winfo_width())

    inner.bind("<Configure>", _on_configure)
    canvas.bind("<Configure>", _on_configure)
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")

    def _on_wheel(event):
        # Only scroll if the content actually exceeds the visible area, AND clamp the result so
        # we don't scroll above the top or below the bottom of the content.
        # tk's yview_scroll is happy to scroll past either edge by default — we have to enforce it.
        bbox = canvas.bbox("all")
        if not bbox:
            return
        content_height = bbox[3] - bbox[1]
        canvas_height = canvas.winfo_height()
        if content_height <= canvas_height:
            return  # nothing to scroll
        # Calculate the new top fraction we'd land at, and clamp [0.0, 1.0 - visible_fraction]
        delta_units = int(-event.delta / 120)
        unit_fraction = 1.0 / max(content_height, 1) * 20  # tk's default scroll unit is ~20px
        current_top = canvas.yview()[0]
        new_top = current_top + delta_units * unit_fraction
        visible_fraction = canvas_height / content_height
        max_top = max(0.0, 1.0 - visible_fraction)
        new_top = max(0.0, min(new_top, max_top))
        canvas.yview_moveto(new_top)

    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    return inner


# ---------------------------------------------------------------------------
# Tabbed pane — custom replacement for ttk.Notebook
# ---------------------------------------------------------------------------

class TabbedPane(tk.Frame):
    """A custom tab widget — replaces ttk.Notebook so we don't pollute the global ttk theme.

    Usage:
        pane = TabbedPane(parent)
        pane.pack(fill="both", expand=True)
        ledger_tab = pane.add_tab("✦ LEDGER")
        # ledger_tab is a Frame — pack content into it as usual
        monthly_tab = pane.add_tab("☷ MONTHLY")
        pane.select(0)  # show first tab
    """

    def __init__(self, parent: tk.Misc, **kw):
        super().__init__(parent, bg=PALETTE["bg"], **kw)
        self._tabs: List[dict] = []  # list of {"button": Button, "frame": Frame}
        self._active_index: Optional[int] = None

        self._tab_bar = tk.Frame(self, bg=PALETTE["bg"])
        self._tab_bar.pack(fill="x")
        self._underline = tk.Frame(self, bg=PALETTE["accent_red_dim"], height=1)
        self._underline.pack(fill="x")
        self._body = tk.Frame(self, bg=PALETTE["bg"])
        self._body.pack(fill="both", expand=True)

    def add_tab(self, label_text: str) -> tk.Frame:
        index = len(self._tabs)
        btn = tk.Label(
            self._tab_bar,
            text=f"  {label_text}  ",
            bg=PALETTE["bg"], fg=PALETTE["fg_dim"],
            font=FONT_HEADER, padx=12, pady=6,
            cursor="hand2",
        )
        btn.pack(side="left")
        btn.bind("<Button-1>", lambda e, i=index: self.select(i))

        page = tk.Frame(self._body, bg=PALETTE["bg"])
        self._tabs.append({"button": btn, "frame": page})

        if index == 0:
            self.select(0)
        return page

    def select(self, index: int) -> None:
        if index < 0 or index >= len(self._tabs):
            return
        # Restyle all tab buttons
        for i, tab in enumerate(self._tabs):
            if i == index:
                tab["button"].configure(
                    fg=PALETTE["accent_red"], bg=PALETTE["bg_card"],
                )
                tab["frame"].pack(fill="both", expand=True)
            else:
                tab["button"].configure(
                    fg=PALETTE["fg_dim"], bg=PALETTE["bg"],
                )
                tab["frame"].pack_forget()
        self._active_index = index
