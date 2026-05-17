"""Shared visual language for DavyJones popup windows.

All widget factories use plain `tk` widgets — no `ttk` — because `ttk.Style().theme_use()` is
PROCESS-WIDE and changing it would re-render every other plugin's ttk widgets. Plain tk widgets
fully respect color attributes, so we get our dark aesthetic without affecting EDMC or BGS-Tally.

The hacker-pirate-codex aesthetic: pitch black, blood red headers, cyan/amber/pink/green data.
"""

import tkinter as tk
from typing import Callable, List, Optional


PALETTE = {
    "bg":            "#0a0a0a",   # near-black main bg
    "bg_alt":        "#141414",   # alternating rows / subtle elevation
    "bg_card":       "#0f0f10",   # cards slightly different from bg
    "bg_input":      "#050505",   # entry/spinbox bg — slightly darker
    "fg":            "#d8d8d8",   # body text — off-white
    "fg_dim":        "#5a5a5a",   # labels / metadata
    "accent_red":    "#c8102e",   # blood red — headers, dividers, primary accents
    "accent_red_dim": "#5a0f1a",  # darker red for borders
    "accent_cyan":   "#5fd7ff",   # primary data — tonnage, counts
    "accent_amber":  "#ffb347",   # credits / value
    "accent_green":  "#4eff8c",   # PvE / success
    "accent_pink":   "#ff5577",   # PvP
    "border":        "#2a0508",   # subtle dark red border
    "border_hot":    "#c8102e",   # emphasised border
}

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
