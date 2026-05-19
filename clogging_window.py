"""Clogging report window — submit a new report or attach/update proof on an existing one."""

import threading
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable, Dict, List, Optional, Tuple

import dj_theme as t

COMBAT_RANKS = [
    "— unknown —",
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly",
    "Elite", "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]


class CloggingWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        cmdr: str,
        scan_history: List[Dict[str, Any]],
        submit_callback: Callable[[Dict[str, Any]], Tuple[bool, str]],
        fetch_reports_callback: Callable[[], List[Dict[str, Any]]],
        update_callback: Callable[[int, Optional[str], bool], Tuple[bool, str]],
    ):
        super().__init__(parent)
        self.title(f"⚠  REPORT CLOGGER  //  {cmdr or 'CMDR'}")
        self.cmdr = cmdr
        self.scan_history = scan_history
        self.submit_callback = submit_callback
        self.fetch_reports_callback = fetch_reports_callback
        self.update_callback = update_callback

        self._selected_scan: Optional[Dict[str, Any]] = None
        self._selected_report: Optional[Dict[str, Any]] = None
        self._selected_report_row: Optional[tk.Frame] = None

        self.configure(bg=t.PALETTE["bg"])
        self.geometry("540x660")
        self.minsize(460, 500)
        self.transient(parent)
        self.grab_set()
        t.restore_or_position(self, key="clogging")
        self.bind("<Destroy>", self._on_destroy)

        self._build_ui()

    def _on_destroy(self, event):
        if event.widget is self:
            t.remember_geometry(self, "clogging")

    def _build_ui(self) -> None:
        outer = t.frame(self)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        t.title_bar(outer, "⚠", "REPORT CLOGGER", self.cmdr)
        t.divider(outer).pack(fill="x", pady=(2, 8))

        pane = t.TabbedPane(outer)
        pane.pack(fill="both", expand=True)

        self._build_new_report_tab(pane.add_tab("✦ NEW REPORT"))
        self._build_my_reports_tab(pane.add_tab("⊞ MY REPORTS"))

    # -------------------------------------------------------------------------
    # NEW REPORT tab
    # -------------------------------------------------------------------------

    def _build_new_report_tab(self, page: tk.Frame) -> None:
        body = t.frame(page)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Target CMDR ---
        t.label(body, text="TARGET COMMANDER",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(4, 2))
        self.cmdr_var = tk.StringVar()
        cmdr_entry = t.entry(body, textvariable=self.cmdr_var)
        cmdr_entry.pack(fill="x", ipady=4)
        cmdr_entry.focus_set()

        # Scan history quick-pick
        hist_header = t.frame(body)
        hist_header.pack(fill="x", pady=(8, 0))
        t.label(hist_header, text=">> RECENT SCANS",
                fg=t.PALETTE["accent_red"], font=t.FONT_HEADER).pack(side="left")
        count = len(self.scan_history)
        t.label(hist_header,
                text=f"   {count} this session" if count else "   none yet",
                fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL).pack(side="left")
        t.divider(body).pack(fill="x", pady=(4, 0))
        self._build_scan_picker(body)

        # --- Reason ---
        t.label(body, text="REASON",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(8, 2))
        reason_frame = tk.Frame(body, bg=t.PALETTE["bg_input"],
                                highlightthickness=1,
                                highlightbackground=t.PALETTE["border"],
                                highlightcolor=t.PALETTE["accent_red"])
        reason_frame.pack(fill="x")
        self.reason_text = tk.Text(
            reason_frame, height=4, wrap="word",
            bg=t.PALETTE["bg_input"], fg=t.PALETTE["fg"],
            insertbackground=t.PALETTE["accent_red"],
            relief=tk.FLAT, borderwidth=0,
            font=t.FONT_BODY,
        )
        self.reason_text.pack(fill="x", padx=4, pady=4)

        # --- Combat rank ---
        t.label(body, text="COMBAT RANK",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(8, 2))
        self.rank_var = tk.StringVar(value="— unknown —")
        t.option_menu(body, self.rank_var, COMBAT_RANKS).pack(anchor="w", fill="x")

        # --- Proof URL ---
        t.label(body, text="PROOF URL  (optional — YouTube, Twitch, Imgur, Discord, Reddit, Streamable)",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(8, 2))
        self.proof_var = tk.StringVar()
        t.entry(body, textvariable=self.proof_var).pack(fill="x", ipady=4)

        # --- Shared ---
        t.label(body, text="VISIBILITY",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(8, 2))
        self.shared_var = tk.StringVar(value="private")
        t.SegmentedRadio(body, self.shared_var, [
            ("private",  "GUILD ONLY",            t.PALETTE["accent_cyan"]),
            ("shared",   "SHARE WITH ALL GUILDS", t.PALETTE["accent_amber"]),
        ]).pack(fill="x")

        # --- Buttons ---
        btns = t.frame(body)
        btns.pack(fill="x", pady=(12, 0))
        t.button(btns, "CANCEL", self.destroy,
                 accent=t.PALETTE["fg_dim"]).pack(side="right", padx=(6, 0))
        t.button(btns, "SUBMIT REPORT", self._submit_new,
                 accent=t.PALETTE["accent_red"]).pack(side="right")

    def _build_scan_picker(self, parent: tk.Frame) -> None:
        container = t.frame(parent)
        container.pack(fill="x")

        if not self.scan_history:
            t.label(container,
                    text=">> NO SCANS THIS SESSION — scan a CMDR in-game to populate",
                    fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL).pack(pady=6)
            return

        canvas = tk.Canvas(container, height=88, bg=t.PALETTE["bg"], bd=0, highlightthickness=0)
        sb = t.scrollbar(container, command=canvas.yview)
        inner = t.frame(canvas)
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _configure(*_):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(wid, width=canvas.winfo_width())

        inner.bind("<Configure>", _configure)
        canvas.bind("<Configure>", _configure)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

        def _bind_wheel(e):
            canvas.bind_all("<MouseWheel>",
                            lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units"))

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        for i, rec in enumerate(self.scan_history):
            cmdr_name = rec["cmdr"]
            rank = rec.get("combat_rank")
            row_bg = t.PALETTE["bg_alt"] if i % 2 else t.PALETTE["bg"]
            row = tk.Frame(inner, bg=row_bg)
            row.pack(fill="x")
            label_text = f"CMDR {cmdr_name}" + (f"  [{rank}]" if rank else "")
            tk.Label(row, text=label_text, anchor="w",
                     fg=t.PALETTE["fg"], bg=row_bg, font=t.FONT_BODY).pack(
                side="left", padx=(4, 0), pady=3)
            t.button(row, "PICK", lambda r=rec: self._pick_scan(r),
                     accent=t.PALETTE["accent_cyan"]).pack(side="right", padx=4, pady=2)

    def _pick_scan(self, record: Dict[str, Any]) -> None:
        self._selected_scan = record
        self.cmdr_var.set(record["cmdr"])
        raw_rank = record.get("combat_rank") or ""
        self.rank_var.set(raw_rank if raw_rank in COMBAT_RANKS else "— unknown —")

    def _submit_new(self) -> None:
        cmdr_name = self.cmdr_var.get().strip()
        if not cmdr_name:
            messagebox.showinfo("DavyJones", "Enter a commander name first.")
            return
        if cmdr_name.lower() == (self.cmdr or "").lower():
            messagebox.showwarning("DavyJones", "You can't report yourself.")
            return
        reason = self.reason_text.get("1.0", tk.END).strip()
        if not reason:
            messagebox.showinfo("DavyJones", "A reason is required.")
            return

        rank = self.rank_var.get()
        proof_url = self.proof_var.get().strip() or None
        shared = self.shared_var.get() == "shared"

        # Use the cached scan record for auto-fill only if it matches the typed name
        scan = (
            self._selected_scan
            if self._selected_scan
            and self._selected_scan["cmdr"].lower() == cmdr_name.lower()
            else None
        )

        payload = {
            "targetCmdr": cmdr_name,
            "reason": reason,
            "targetCombatRank": rank if rank != "— unknown —" else None,
            "starSystem": scan["system"] if scan else None,
            "station": scan["station"] if scan else None,
            "proofUrl": proof_url,
            "shared": shared,
        }

        def worker():
            ok, msg = self.submit_callback(payload)
            self.after(0, lambda: self._handle_submit_result(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_submit_result(self, ok: bool, msg: str) -> None:
        if ok:
            messagebox.showinfo("DavyJones", msg)
            self.destroy()
        else:
            messagebox.showerror("DavyJones", f"Failed to submit report:\n{msg}")

    # -------------------------------------------------------------------------
    # MY REPORTS tab
    # -------------------------------------------------------------------------

    def _build_my_reports_tab(self, page: tk.Frame) -> None:
        body = t.frame(page)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        # Load row
        load_row = t.frame(body)
        load_row.pack(fill="x", pady=(4, 0))
        t.button(load_row, "⟳  LOAD MY REPORTS", self._load_reports).pack(side="left")
        self._load_status = t.label(load_row, text="",
                                    fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL)
        self._load_status.pack(side="left", padx=10)
        t.divider(body).pack(fill="x", pady=(6, 0))

        # Scrollable reports list — fixed height so the edit area always stays visible
        list_container = t.frame(body)
        list_container.pack(fill="x")

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
        reports_canvas.pack(side="left", fill="x", expand=True)
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

        # Edit area
        t.divider(body).pack(fill="x", pady=(8, 6))

        t.label(body, text="EDIT SELECTED REPORT",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(0, 2))

        self._edit_target_label = t.label(body, text="— select a report above —",
                                          fg=t.PALETTE["fg_dim"], font=t.FONT_LABEL)
        self._edit_target_label.pack(anchor="w", pady=(0, 6))

        t.label(body, text="PROOF URL",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(0, 2))
        self.edit_proof_var = tk.StringVar()
        t.entry(body, textvariable=self.edit_proof_var).pack(fill="x", ipady=4)

        t.label(body, text="VISIBILITY",
                fg=t.PALETTE["accent_red"], font=t.FONT_BADGE).pack(anchor="w", pady=(8, 2))
        self.edit_shared_var = tk.StringVar(value="private")
        t.SegmentedRadio(body, self.edit_shared_var, [
            ("private", "GUILD ONLY",            t.PALETTE["accent_cyan"]),
            ("shared",  "SHARE WITH ALL GUILDS", t.PALETTE["accent_amber"]),
        ]).pack(fill="x")

        btns = t.frame(body)
        btns.pack(fill="x", pady=(12, 0))
        t.button(btns, "UPDATE REPORT", self._update_selected,
                 accent=t.PALETTE["accent_red"]).pack(side="right")

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
        self._selected_report = None
        self._selected_report_row = None

        if not reports:
            t.label(self._reports_inner, text="No recent reports (last 30 days).",
                    fg=t.PALETTE["fg_dim"]).pack(pady=16)
            self._load_status.config(text="0 reports", fg=t.PALETTE["fg_dim"])
            return

        self._load_status.config(text=f"{len(reports)} report(s)", fg=t.PALETTE["fg_dim"])

        for i, rep in enumerate(reports):
            row_bg = t.PALETTE["bg_alt"] if i % 2 else t.PALETTE["bg"]
            row = tk.Frame(self._reports_inner, bg=row_bg, cursor="hand2")
            row._orig_bg = row_bg  # used by _select_report to restore on deselect
            row.pack(fill="x")

            cmdr = rep.get("targetCmdr", "?")
            reason_raw = rep.get("reason", "")
            reason_preview = reason_raw[:42] + ("…" if len(reason_raw) > 42 else "")
            proof_icon = "✓ proof" if rep.get("proofUrl") else "— no proof"
            shared_icon = "shared" if rep.get("shared") else "guild"
            meta = f"  {proof_icon}  ·  {shared_icon}"

            tk.Label(row, text=f"CMDR {cmdr}", anchor="w",
                     fg=t.PALETTE["accent_cyan"], bg=row_bg, font=t.FONT_BODY).pack(
                side="left", padx=(6, 0), pady=(4, 0))
            tk.Label(row, text=meta, anchor="w",
                     fg=t.PALETTE["fg_dim"], bg=row_bg, font=t.FONT_LABEL).pack(
                side="right", padx=(0, 6), pady=(4, 0))

            tk.Label(row, text=reason_preview, anchor="w",
                     fg=t.PALETTE["fg_dim"], bg=row_bg, font=t.FONT_LABEL).pack(
                side="left", padx=(6, 0), pady=(0, 4))

            # Bind click on the frame AND every child label — child widgets don't
            # propagate Button-1 to the parent in Tk, so each must be bound explicitly.
            for widget in (row, *row.winfo_children()):
                widget.bind("<Button-1>", lambda e, r=rep, fr=row: self._select_report(r, fr))

    def _select_report(self, report: Dict[str, Any], row: tk.Frame) -> None:
        # Deselect previous
        if self._selected_report_row:
            prev_bg = getattr(self._selected_report_row, "_orig_bg", t.PALETTE["bg"])
            try:
                self._selected_report_row.configure(bg=prev_bg)
                for child in self._selected_report_row.winfo_children():
                    child.configure(bg=prev_bg)
            except tk.TclError:
                pass

        self._selected_report = report
        self._selected_report_row = row

        # Highlight selected row
        for widget in (row, *row.winfo_children()):
            try:
                widget.configure(bg=t.PALETTE["accent_red_dim"])
            except tk.TclError:
                pass

        # Populate edit fields
        self.edit_proof_var.set(report.get("proofUrl") or "")
        self.edit_shared_var.set("shared" if report.get("shared") else "private")
        self._edit_target_label.config(
            text=f"editing: CMDR {report.get('targetCmdr', '?')}",
            fg=t.PALETTE["accent_cyan"],
        )

    def _update_selected(self) -> None:
        if not self._selected_report:
            messagebox.showinfo("DavyJones", "Select a report from the list first.")
            return

        report_id = self._selected_report.get("id")
        proof_url = self.edit_proof_var.get().strip() or None
        shared = self.edit_shared_var.get() == "shared"

        def worker():
            ok, msg = self.update_callback(report_id, proof_url, shared)
            self.after(0, lambda: self._handle_update_result(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_update_result(self, ok: bool, msg: str) -> None:
        if ok:
            messagebox.showinfo("DavyJones", msg)
            self._load_reports()
        else:
            messagebox.showerror("DavyJones", f"Failed to update report:\n{msg}")
