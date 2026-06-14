"""Plunder report window. Shows current cargo, lets the user mark loot quantities and submit.

Aesthetic matches stats_window — pitch black, blood red headers, cyan tonnage, amber values.
"""

import tkinter as tk
from tkinter import messagebox
from typing import Callable, Dict, Tuple

import dj_theme as t


class CargoReportWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        cargo: Dict[str, dict],
        cmdr: str,
        submit_callback: Callable[[dict], Tuple[bool, str]],
    ):
        super().__init__(parent)
        self.title(f"⚓  REPORT PLUNDER  //  {cmdr or 'CMDR'}")
        self.cargo = cargo
        self.cmdr = cmdr
        self.submit_callback = submit_callback
        self.entries: Dict[str, tk.IntVar] = {}
        self.kind_var = tk.StringVar(value="PvE")

        self.configure(bg=t.PALETTE["bg"])
        self.geometry("520x600")
        self.minsize(480, 480)
        self.transient(parent)
        self.grab_set()
        t.restore_or_position(self, key="plunder")
        self.bind("<Destroy>", self._on_destroy)

        self._build_ui()

    def _on_destroy(self, event):
        # Only capture geometry for THIS window's Destroy, not children's bubbling up
        if event.widget is self:
            t.remember_geometry(self, "plunder")    

    def _build_ui(self) -> None:
        outer = t.frame(self)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        # --- Buttons ---
        # Packed first with side="bottom" so the action bar always sits flush to the
        # bottom of the window, even when the cargo list is short or the hold is empty.
        # The cargo content below fills the space above it.
        btns = t.frame(outer)
        btns.pack(side="bottom", fill="x", pady=(14, 0))
        t.button(btns, "CANCEL", self.destroy,
                 accent=t.PALETTE["fg"]).pack(side="right", padx=(6, 0))
        t.button(btns, "SUBMIT", self._submit,
                 accent=t.PALETTE["accent_red"]).pack(side="right")

        # --- Title bar ---
        t.title_bar(outer, "☠", "REPORT PLUNDER", self.cmdr)
        t.divider(outer).pack(fill="x", pady=(2, 12))

        # --- Type section ---
        meta = t.frame(outer)
        meta.pack(fill="x", pady=(0, 14))

        t.label(meta, text="TYPE",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(0, 4))

        t.SegmentedRadio(meta, self.kind_var, [
            ("PvE", "PvE", t.PALETTE["accent_green"]),
            ("PvP", "PvP", t.PALETTE["accent_pink"]),
        ]).pack(anchor="w", fill="x")

        # --- Cargo section ---
        cargo_header = t.frame(outer)
        cargo_header.pack(fill="x")
        t.label(
            cargo_header, text=">> MARK YOUR PLUNDER",
            fg=t.PALETTE["accent_red"], font=t.FONT_HEADER,
        ).pack(side="left")
        t.label(
            cargo_header,
            text=f"   {sum(i['count'] for i in self.cargo.values())}t in hold" if self.cargo else "",
            fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL,
        ).pack(side="left")
        t.divider(outer).pack(fill="x", pady=(4, 6))

        if not self.cargo:
            t.label(
                outer,
                text=">> CARGO HOLD EMPTY\nopen cargo panel in-game to refresh",
                fg=t.PALETTE["fg_dim"], font=t.FONT_BODY, justify="center",
            ).pack(pady=30)
        else:
            self._render_cargo_list(outer)

    def _render_cargo_list(self, parent: tk.Misc) -> None:
        # Column header
        header = t.frame(parent)
        header.pack(fill="x", padx=4, pady=(0, 4))
        cols = [
            ("ITEM",        24, "w"),
            ("HOLD",        8,  "w"),
            ("PLUNDERED",   12, "w"),
            ("",            6,  "w"),
        ]
        for c, (text, w, anchor) in enumerate(cols):
            tk.Label(
                header, text=text, width=w, anchor=anchor,
                fg=t.PALETTE["accent_red"], bg=t.PALETTE["bg"],
                font=t.FONT_BADGE,
            ).grid(row=0, column=c, sticky="w")

        # Scrollable cargo list
        body = t.make_scrollable(parent)
        for r, (fdev_id, info) in enumerate(sorted(self.cargo.items(), key=lambda kv: kv[1]["display"])):
            row_bg = t.PALETTE["bg_alt"] if r % 2 else t.PALETTE["bg"]
            row = tk.Frame(body, bg=row_bg)
            row.pack(fill="x", padx=4)

            count = info["count"]
            display = info["display"]
            var = tk.IntVar(value=0)
            self.entries[fdev_id] = var  # key by FDevID — that's what we submit

            tk.Label(
                row, text=display, width=24, anchor="w",
                fg=t.PALETTE["fg"], bg=row_bg, font=t.FONT_BODY,
            ).grid(row=0, column=0, sticky="w", pady=2)
            tk.Label(
                row, text=f"{count}t", width=8, anchor="w",
                fg=t.PALETTE["fg_dim"], bg=row_bg, font=t.FONT_BODY,
            ).grid(row=0, column=1, sticky="w", pady=2)
            spin = t.spinbox(row, from_=0, to=count, textvariable=var, width=10)
            spin.grid(row=0, column=2, sticky="w", pady=2, padx=(0, 4))
            t.button(
                row, "ALL",
                lambda v=var, c=count: v.set(c),
                accent=t.PALETTE["accent_cyan"],
            ).grid(row=0, column=3, sticky="w", pady=2)

    def _submit(self) -> None:
        items = [
            {"commodity": name, "count": var.get()}
            for name, var in self.entries.items()
            if var.get() > 0
        ]
        if not items:
            messagebox.showinfo("DavyJones", "Nothing marked. Set at least one quantity.")
            return

        payload = {
            "kind": self.kind_var.get(),
            "items": items,
        }
        ok, msg = self.submit_callback(payload)
        if ok:
            messagebox.showinfo("DavyJones", msg)
            self.destroy()
        else:
            messagebox.showerror("DavyJones", f"Submit failed:\n{msg}")
