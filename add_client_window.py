"""Add Client window. Lets a user submit a CMDR name to the squadron client list, and
browse their own recent client reports.

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
        fetch_reports_callback: Callable[[], List[Dict[str, Any]]],
    ):
        super().__init__(parent)
        self.title(f"⚓  ADD CLIENT  //  {cmdr or 'CMDR'}")
        self.cmdr = cmdr
        self.scan_history = scan_history
        self.submit_callback = submit_callback
        self.fetch_reports_callback = fetch_reports_callback
        self.cmdr_var = tk.StringVar(value="")
        self.complied_var = tk.StringVar(value="complied")  # "complied" | "hatchbreak"

        self.configure(bg=t.PALETTE["bg"])
        self.geometry("500x620")
        self.minsize(440, 480)
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
        t.divider(outer).pack(fill="x", pady=(2, 8))

        pane = t.TabbedPane(outer)
        pane.pack(fill="both", expand=True)

        self._build_add_tab(pane.add_tab("✦ ADD CLIENT"))
        self._build_my_reports_tab(pane.add_tab("⊞ MY REPORTS"))

    # -------------------------------------------------------------------------
    # ADD CLIENT tab
    # -------------------------------------------------------------------------

    def _build_add_tab(self, page: tk.Frame) -> None:
        body = t.frame(page)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Manual entry ---
        t.label(
            body, text="COMMANDER NAME",
            fg=t.PALETTE["accent_red"], font=t.FONT_BADGE,
        ).pack(anchor="w", pady=(0, 2))
        cmdr_entry = t.entry(body, textvariable=self.cmdr_var)
        cmdr_entry.pack(fill="x", ipady=4)
        cmdr_entry.focus_set()
        cmdr_entry.bind("<Return>", lambda e: self._submit())

        t.label(
            body, text="enter name exactly as it appears in-game (CMDR prefix stripped)",
            fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL,
        ).pack(anchor="w", pady=(2, 14))

        # --- Compliance ---
        t.label(
            body, text="OUTCOME",
            fg=t.PALETTE["accent_red"], font=t.FONT_BADGE,
        ).pack(anchor="w", pady=(0, 4))

        t.SegmentedRadio(body, self.complied_var, [
            ("complied",   "COMPLIED",   t.PALETTE["accent_green"]),
            ("hatchbreak", "HATCHBREAK", t.PALETTE["accent_pink"]),
        ]).pack(anchor="w", fill="x", pady=(0, 14))

        # --- Buttons — packed before the expandable history so they anchor to the bottom ---
        btns = t.frame(body)
        btns.pack(side="bottom", fill="x", pady=(14, 0))
        t.button(btns, "CANCEL", self.destroy,
                 accent=t.PALETTE["fg"]).pack(side="right", padx=(6, 0))
        t.button(btns, "SUBMIT", self._submit,
                 accent=t.PALETTE["accent_red"]).pack(side="right")

        # --- Scan history ---
        history_header = t.frame(body)
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
        t.divider(body).pack(fill="x", pady=(4, 6))

        if not self.scan_history:
            t.label(
                body,
                text=">> NO SCANS THIS SESSION\nscanned commanders will appear here",
                fg=t.PALETTE["fg_dim"], font=t.FONT_BODY, justify="center",
            ).pack(pady=20)
        else:
            self._render_history(body)

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

    # -------------------------------------------------------------------------
    # MY REPORTS tab
    # -------------------------------------------------------------------------

    def _build_my_reports_tab(self, page: tk.Frame) -> None:
        body = t.frame(page)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        load_row = t.frame(body)
        load_row.pack(fill="x", pady=(4, 0))
        t.button(load_row, "⟳  LOAD MY REPORTS", self._load_reports).pack(side="left")
        self._load_status = t.label(load_row, text="",
                                    fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL)
        self._load_status.pack(side="left", padx=10)
        t.divider(body).pack(fill="x", pady=(6, 0))

        list_container = t.frame(body)
        list_container.pack(fill="both", expand=True)

        reports_canvas = tk.Canvas(list_container, height=200,
                                   bg=t.PALETTE["bg"], bd=0, highlightthickness=0)
        reports_sb = t.scrollbar(list_container, command=reports_canvas.yview)
        self._reports_inner = t.frame(reports_canvas)
        wid = reports_canvas.create_window((0, 0), window=self._reports_inner, anchor="nw")

        def _configure(*_):
            reports_canvas.configure(scrollregion=reports_canvas.bbox("all"))
            reports_canvas.itemconfigure(wid, width=reports_canvas.winfo_width())

        self._reports_inner.bind("<Configure>", _configure)
        reports_canvas.bind("<Configure>", _configure)
        reports_canvas.configure(yscrollcommand=reports_sb.set)
        reports_canvas.pack(side="left", fill="both", expand=True)
        reports_sb.pack(side="right", fill="y")

        def _bind_wheel(e):
            reports_canvas.bind_all(
                "<MouseWheel>",
                lambda ev: reports_canvas.yview_scroll(int(-ev.delta / 120), "units"),
            )

        reports_canvas.bind("<Enter>", _bind_wheel)
        reports_canvas.bind("<Leave>", lambda e: reports_canvas.unbind_all("<MouseWheel>"))

        t.label(self._reports_inner,
                text="Press  ⟳ LOAD MY REPORTS  to see your recent reports.",
                fg=t.PALETTE["fg_dim"]).pack(pady=16)

    def _load_reports(self) -> None:
        self._load_status.config(text="loading…", fg=t.PALETTE["fg_dim"])

        def worker():
            try:
                reports = self.fetch_reports_callback()
                self.after(0, lambda: self._render_reports(reports))
            except Exception as e:
                self.after(0, lambda err=e: self._load_status.config(
                    text=f"error: {err}", fg="red"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_reports(self, reports: List[Dict[str, Any]]) -> None:
        for w in self._reports_inner.winfo_children():
            w.destroy()

        if not reports:
            t.label(self._reports_inner, text="No recent reports (last 30 days).",
                    fg=t.PALETTE["fg_dim"]).pack(pady=16)
            self._load_status.config(text="0 reports (last 30 days)", fg=t.PALETTE["fg_dim"])
            return

        self._load_status.config(text=f"{len(reports)} report(s) (last 30 days)", fg=t.PALETTE["fg_dim"])

        for i, rep in enumerate(reports):
            row_bg = t.PALETTE["bg_alt"] if i % 2 else t.PALETTE["bg"]
            row = tk.Frame(self._reports_inner, bg=row_bg)
            row.pack(fill="x")

            cmdr = rep.get("cmdrName", "?")
            complied = bool(rep.get("complied"))
            outcome_text = "complied" if complied else "hatchbreak"
            outcome_color = t.PALETTE["accent_green"] if complied else t.PALETTE["accent_pink"]
            on_cooldown = bool(rep.get("onCooldown"))
            cooldown_text = "⛔ on cooldown" if on_cooldown else "cooldown clear"
            cooldown_color = t.PALETTE["accent_amber"] if on_cooldown else t.PALETTE["fg_dim"]
            reported_at = rep.get("reportedAtRelative") or rep.get("reportedAt") or "—"

            tk.Label(row, text=f"CMDR {cmdr}", anchor="w",
                     fg=t.PALETTE["accent_cyan"], bg=row_bg, font=t.FONT_BODY).pack(
                side="left", padx=(6, 0), pady=(4, 2))
            tk.Label(row, text=outcome_text, anchor="e",
                     fg=outcome_color, bg=row_bg, font=t.FONT_LABEL).pack(
                side="right", padx=(0, 6), pady=(4, 2))

            meta = f"{cooldown_text}  ·  reported {reported_at}"
            tk.Label(row, text=meta, anchor="w",
                     fg=cooldown_color, bg=row_bg, font=t.FONT_LABEL).pack(
                side="left", padx=(6, 0), pady=(0, 4))
