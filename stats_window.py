"""Commander stats window. Headline numbers, ledger, monthly breakdown.

Aesthetic owned by dj_theme.py — keep visual decisions there, layout decisions here.
"""

import threading
import tkinter as tk
from typing import Callable, Dict, List, Any, Optional

import dj_theme as t


def _fmt_credits(n: Any) -> str:
    try:
        return f"{int(n):,} Cr"
    except (TypeError, ValueError):
        return "—"


def _fmt_tonnage(n: Any) -> str:
    try:
        return f"{int(n):,} t"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(n: Any) -> str:
    try:
        return f"{float(n):.0f}%"
    except (TypeError, ValueError):
        return "—"


class StatsWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        cmdr: str,
        fetch_callback: Callable[[], Optional[Dict[str, Any]]],
    ):
        super().__init__(parent)
        self.title(f"⚓  DAVY JONES LOCKER  //  {cmdr or 'CMDR'}")
        self.cmdr = cmdr
        self.fetch_callback = fetch_callback

        self.configure(bg=t.PALETTE["bg"])
        self.geometry("720x640")
        self.minsize(640, 540)
        self.transient(parent)
        self.grab_set()
        t.restore_or_position(self, key="stats")
        self.bind("<Destroy>", self._on_destroy)

        self._loading_label: Optional[tk.Label] = None
        self._build_loading()
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _on_destroy(self, event):
        # Only capture geometry for THIS window's Destroy, not children's bubbling up
        if event.widget is self:
            t.remember_geometry(self, "stats")

    # ------------------------------------------------------------------
    def _build_loading(self) -> None:
        self._loading_label = t.label(
            self, text=">> ACCESSING LOCKER...",
            fg=t.PALETTE["accent_cyan"], font=t.FONT_HEADER,
        )
        self._loading_label.pack(expand=True)

    def _fetch_worker(self) -> None:
        try:
            data = self.fetch_callback()
        except Exception as e:
            self.after(0, lambda: self._show_error(str(e)))
            return
        if data is None:
            self.after(0, lambda: self._show_error("No data returned."))
            return
        self.after(0, lambda: self._render(data))

    def _show_error(self, msg: str) -> None:
        if self._loading_label:
            self._loading_label.destroy()
            self._loading_label = None
        wrap = t.frame(self)
        wrap.pack(expand=True, fill="both", padx=40, pady=40)
        t.label(
            wrap, text=">> CONNECTION LOST",
            fg=t.PALETTE["accent_red"], font=t.FONT_BIG,
        ).pack(pady=(0, 8))
        t.label(
            wrap, text=msg, fg=t.PALETTE["fg_dim"], font=t.FONT_BODY,
            wraplength=500, justify="center",
        ).pack()
        t.button(wrap, "CLOSE", self.destroy, accent=t.PALETTE["fg"]).pack(pady=20)

    # ------------------------------------------------------------------
    def _render(self, data: Dict[str, Any]) -> None:
        if self._loading_label:
            self._loading_label.destroy()
            self._loading_label = None

        outer = t.frame(self)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        t.title_bar(outer, "☠", "COMMANDER LEDGER",
                    data.get("cmdr") or self.cmdr)
        t.divider(outer).pack(fill="x", pady=(2, 12))

        self._render_headlines(outer, data.get("totals") or {})

        pane = t.TabbedPane(outer)
        pane.pack(fill="both", expand=True, pady=(14, 0))

        ledger_tab = pane.add_tab("✦ LEDGER")
        self._render_ledger(ledger_tab, data.get("ledger") or [])

        monthly_tab = pane.add_tab("☷ MONTHLY")
        self._render_monthly(monthly_tab, data.get("monthly") or [])

        footer = t.frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        t.button(footer, "CLOSE", self.destroy, accent=t.PALETTE["fg"]).pack(side="right")

    # ------------------------------------------------------------------
    def _render_headlines(self, parent: tk.Misc, totals: Dict[str, Any]) -> None:
        wrap = t.frame(parent)
        wrap.pack(fill="x")

        cards = [
            ("TONNAGE",  _fmt_tonnage(totals.get("tonnage")),   t.PALETTE["accent_cyan"]),
            ("PROFIT",   _fmt_credits(totals.get("value")),     t.PALETTE["accent_amber"]),
            ("TOP HAUL", str(totals.get("mostLooted") or "—"),  t.PALETTE["accent_cyan"]),
            ("ITEMS",    str(totals.get("itemsCount") or 0),    t.PALETTE["accent_cyan"]),
            ("PvP",      _fmt_pct(totals.get("pvpPct")),        t.PALETTE["accent_pink"]),
            ("PvE",      _fmt_pct(totals.get("pvePct")),        t.PALETTE["accent_green"]),
        ]
        for col, (lbl, value, color) in enumerate(cards):
            card = tk.Frame(
                wrap, bg=t.PALETTE["bg_card"],
                highlightbackground=t.PALETTE["border"],
                highlightthickness=1,
            )
            card.grid(row=0, column=col, sticky="nsew", padx=3, pady=2)
            tk.Frame(card, bg=color, height=2).pack(fill="x")
            t.label(
                card, text=value, fg=color, bg=t.PALETTE["bg_card"],
                font=t.FONT_BIG,
            ).pack(pady=(8, 0), padx=8)
            t.label(
                card, text=lbl, fg=t.PALETTE["fg_dim"], bg=t.PALETTE["bg_card"],
                font=t.FONT_LABEL,
            ).pack(pady=(2, 8), padx=8)
            wrap.columnconfigure(col, weight=1)

    # ------------------------------------------------------------------
    def _render_ledger(self, parent: tk.Misc, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            t.label(
                parent, text=">> NO ENTRIES IN LOCKER",
                fg=t.PALETTE["fg_dim"], font=t.FONT_HEADER,
            ).pack(pady=40)
            return

        # Headers and body share the same grid columns inside the scrollable canvas, so widths
        # auto-sync. (Using two separate frames with `width=N chars` doesn't align reliably
        # because the header uses a bold font and body cells use a regular font — same character
        # count, different pixel widths.)
        body = t.make_scrollable(parent)

        # Column definitions: (header label, weight, anchor)
        cols = [
            ("DATE / TIME", 2,  "w"),
            ("ITEM",        3,  "w"),
            ("RARITY",      1,  "w"),
            ("TYPE",        1,  "w"),
            ("TONNAGE",     1,  "e"),  # right-align numeric columns
            ("VALUE",       2,  "e"),
        ]
        for c, (header_text, weight, anchor) in enumerate(cols):
            body.columnconfigure(c, weight=weight, uniform="ledger")

        # Header row
        for c, (header_text, weight, anchor) in enumerate(cols):
            tk.Label(
                body, text=header_text, anchor=anchor,
                fg=t.PALETTE["accent_red"], bg=t.PALETTE["bg"],
                font=t.FONT_BADGE,
            ).grid(row=0, column=c, sticky="we", padx=8, pady=(4, 6))

        # Underline separator
        sep = tk.Frame(body, bg=t.PALETTE["accent_red_dim"], height=1)
        sep.grid(row=1, column=0, columnspan=len(cols), sticky="we", padx=8)

        # Body rows — each cell is its own widget, so we can paint per-cell bg for stripes
        for r, entry in enumerate(entries):
            row_idx = r + 2  # leave row 0 = header, row 1 = separator
            row_bg = t.PALETTE["bg_alt"] if r % 2 else t.PALETTE["bg"]

            kind = (entry.get("kind") or "").upper()
            kind_color = (
                t.PALETTE["accent_pink"] if kind == "PVP"
                else t.PALETTE["accent_green"] if kind == "PVE"
                else t.PALETTE["fg_dim"]
            )

            cells = [
                # (text, fg, font, anchor)
                (f"{entry.get('date', '')} {entry.get('time', '')}".strip(),
                 t.PALETTE["fg_dim"], t.FONT_BODY, "w"),
                (str(entry.get("item", "—")),
                 t.PALETTE["fg"], t.FONT_BODY, "w"),
                (str(entry.get("rarity", "—")),
                 self._rarity_color(entry.get("rarity")), t.FONT_BADGE, "w"),
                (kind or "—",
                 kind_color, t.FONT_BADGE, "w"),
                (_fmt_tonnage(entry.get("tonnage")),
                 t.PALETTE["accent_cyan"], t.FONT_BODY, "e"),
                (_fmt_credits(entry.get("value")),
                 t.PALETTE["accent_amber"], t.FONT_BODY, "e"),
            ]
            for c, (text, fg, font, anchor) in enumerate(cells):
                tk.Label(
                    body, text=text, anchor=anchor,
                    fg=fg, bg=row_bg, font=font,
                ).grid(row=row_idx, column=c, sticky="we", padx=8, pady=1, ipady=1)

    def _rarity_color(self, rarity: Any) -> str:
        r = (str(rarity) or "").lower()
        if r == "common":    return t.PALETTE["accent_green"]
        if r == "uncommon":  return t.PALETTE["accent_cyan"]
        if r == "rare":      return t.PALETTE["accent_amber"]
        if r == "legendary": return t.PALETTE["accent_red"]
        return t.PALETTE["fg_dim"]

    # ------------------------------------------------------------------
    def _render_monthly(self, parent: tk.Misc, months: List[Dict[str, Any]]) -> None:
        if not months:
            t.label(
                parent, text=">> NO MONTHLY DATA",
                fg=t.PALETTE["fg_dim"], font=t.FONT_HEADER,
            ).pack(pady=40)
            return

        body = t.make_scrollable(parent)
        for m in months:
            is_current = bool(m.get("current"))
            border = t.PALETTE["border_hot"] if is_current else t.PALETTE["border"]
            thickness = 2 if is_current else 1

            card = tk.Frame(
                body, bg=t.PALETTE["bg_card"],
                highlightbackground=border, highlightthickness=thickness,
            )
            card.pack(fill="x", padx=8, pady=6)

            header = tk.Frame(card, bg=t.PALETTE["bg_card"])
            header.pack(fill="x", padx=10, pady=(8, 4))
            title_text = str(m.get("label") or m.get("month") or "?").upper()
            tk.Label(
                header, text=f"✦ {title_text}",
                fg=t.PALETTE["accent_red"] if is_current else t.PALETTE["fg"],
                bg=t.PALETTE["bg_card"], font=t.FONT_BIG,
            ).pack(side="left")
            if is_current:
                tk.Label(
                    header, text=" ACTIVE ",
                    bg=t.PALETTE["accent_red"], fg=t.PALETTE["bg"],
                    font=t.FONT_BADGE, padx=4,
                ).pack(side="right")

            stats = tk.Frame(card, bg=t.PALETTE["bg_card"])
            stats.pack(fill="x", padx=10, pady=(2, 10))
            cells = [
                ("PvP TONNAGE", _fmt_tonnage(m.get("pvpTonnage")), t.PALETTE["accent_pink"]),
                ("PvP VALUE",   _fmt_credits(m.get("pvpValue")),   t.PALETTE["accent_amber"]),
                ("PvE TONNAGE", _fmt_tonnage(m.get("pveTonnage")), t.PALETTE["accent_green"]),
                ("PvE VALUE",   _fmt_credits(m.get("pveValue")),   t.PALETTE["accent_amber"]),
            ]
            for c, (lbl, value, color) in enumerate(cells):
                cell = tk.Frame(stats, bg=t.PALETTE["bg_card"])
                cell.grid(row=0, column=c, sticky="we", padx=2)
                tk.Label(
                    cell, text=lbl, bg=t.PALETTE["bg_card"],
                    fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL,
                ).pack(anchor="w")
                tk.Label(
                    cell, text=value, bg=t.PALETTE["bg_card"],
                    fg=color, font=t.FONT_HEADER,
                ).pack(anchor="w")
                stats.columnconfigure(c, weight=1)
