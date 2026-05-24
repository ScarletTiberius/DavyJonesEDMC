"""Add Client window. Lets a user submit a CMDR name to the squadron client list.

Surfaces recently scanned CMDRs as quick-pick suggestions — saves typing and reduces typos
(important since the client list is keyed by exact name match).
"""

import threading
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable, Dict, List, Tuple

import dj_theme as t


class AddClientWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        cmdr: str,
        scan_history: List[Dict[str, Any]],
        submit_callback: Callable[[str, bool], Tuple[bool, str]],
    ):
        super().__init__(parent)
        self.title(f"⚓  ADD CLIENT  //  {cmdr or 'CMDR'}")
        self.cmdr = cmdr
        self.scan_history = scan_history
        self.submit_callback = submit_callback
        self.cmdr_var = tk.StringVar(value="")
        self.complied_var = tk.StringVar(value="complied")  # "complied" | "hatchbreak"

        self.configure(bg=t.PALETTE["bg"])
        self.geometry("480x500")
        self.minsize(420, 360)
        self.transient(parent)
        self.grab_set()
        t.restore_or_position(self, key="add_client")
        self.bind("<Destroy>", self._on_destroy)

        self._build_ui()

    def _on_destroy(self, event):
        # Only capture geometry for THIS window's Destroy, not children's bubbling up
        if event.widget is self:
            t.remember_geometry(self, "add_client")

    def _build_ui(self) -> None:
        outer = t.frame(self)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        # --- Title ---
        t.title_bar(outer, "☠", "ADD CLIENT", self.cmdr)
        t.divider(outer).pack(fill="x", pady=(2, 12))

        # --- Manual entry ---
        t.label(
            outer, text="COMMANDER NAME",
            fg=t.PALETTE["accent_red"], font=t.FONT_BADGE,
        ).pack(anchor="w", pady=(0, 2))
        cmdr_entry = t.entry(outer, textvariable=self.cmdr_var)
        cmdr_entry.pack(fill="x", ipady=4)
        cmdr_entry.focus_set()
        cmdr_entry.bind("<Return>", lambda e: self._submit())

        t.label(
            outer, text="enter name exactly as it appears in-game (CMDR prefix stripped)",
            fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL,
        ).pack(anchor="w", pady=(2, 14))

        # --- Compliance ---
        t.label(
            outer, text="OUTCOME",
            fg=t.PALETTE["accent_red"], font=t.FONT_BADGE,
        ).pack(anchor="w", pady=(0, 4))

        t.SegmentedRadio(outer, self.complied_var, [
            ("complied",   "COMPLIED",   t.PALETTE["accent_green"]),
            ("hatchbreak", "HATCHBREAK", t.PALETTE["accent_pink"]),
        ]).pack(anchor="w", fill="x", pady=(0, 14))

        # --- Buttons — packed before the expandable history so they anchor to the bottom ---
        btns = t.frame(outer)
        btns.pack(side="bottom", fill="x", pady=(14, 0))
        t.button(btns, "CANCEL", self.destroy,
                 accent=t.PALETTE["fg_dim"]).pack(side="right", padx=(6, 0))
        t.button(btns, "ADD", self._submit,
                 accent=t.PALETTE["accent_red"]).pack(side="right")

        # --- Scan history ---
        history_header = t.frame(outer)
        history_header.pack(fill="x")
        t.label(
            history_header, text=">> RECENT SCANS",
            fg=t.PALETTE["accent_red"], font=t.FONT_HEADER,
        ).pack(side="left")
        count = len(self.scan_history)
        t.label(
            history_header,
            text=f"   {count} this session" if count else "   none yet",
            fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL,
        ).pack(side="left")
        t.divider(outer).pack(fill="x", pady=(4, 6))

        if not self.scan_history:
            t.label(
                outer,
                text=">> NO SCANS THIS SESSION\nscanned commanders will appear here",
                fg=t.PALETTE["fg_dim"], font=t.FONT_BODY, justify="center",
            ).pack(pady=20)
        else:
            self._render_history(outer)

    def _render_history(self, parent: tk.Misc) -> None:
        body = t.make_scrollable(parent)
        for r, rec in enumerate(self.scan_history):
            cmdr_name = rec["cmdr"]
            rank = rec.get("combat_rank")
            row_bg = t.PALETTE["bg_alt"] if r % 2 else t.PALETTE["bg"]
            row = tk.Frame(body, bg=row_bg)
            row.pack(fill="x", padx=4)

            label_text = f"CMDR {cmdr_name}" + (f"  [{rank}]" if rank else "")
            tk.Label(
                row, text=label_text, anchor="w",
                fg=t.PALETTE["fg"], bg=row_bg, font=t.FONT_BODY,
            ).pack(side="left", padx=(4, 0), pady=4)

            # The "pick" action — fills the entry box, doesn't auto-submit.
            # Letting the user click pick → ADD gives them a sanity check before submitting.
            t.button(
                row, "PICK",
                lambda n=cmdr_name: self.cmdr_var.set(n),
                accent=t.PALETTE["accent_cyan"],
            ).pack(side="right", padx=4, pady=2)

    def _submit(self) -> None:
        cmdr_name = self.cmdr_var.get().strip()
        if not cmdr_name:
            messagebox.showinfo("DavyJones", "Enter a commander name first.")
            return

        if cmdr_name.lower() == (self.cmdr or "").lower():
            messagebox.showwarning("DavyJones", "You can't add yourself as a client.")
            return

        # Confirm before posting — client list is a community resource, typos hurt
        outcome = "complied" if self.complied_var.get() == "complied" else "required a hatchbreak"
        if not messagebox.askyesno(
            "DavyJones",
            f"Add CMDR {cmdr_name} to the squadron client list?\n\nOutcome: {outcome}",
        ):
            return

        # Run the actual API call in a thread so the UI stays responsive on slow connections
        complied = self.complied_var.get() == "complied"

        def worker():
            ok, msg = self.submit_callback(cmdr_name, complied)
            self.after(0, lambda: self._handle_result(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_result(self, ok: bool, msg: str) -> None:
        if ok:
            messagebox.showinfo("DavyJones", msg)
            self.destroy()
        else:
            messagebox.showerror("DavyJones", f"Failed to add client:\n{msg}")
