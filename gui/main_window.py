"""提醒列表主窗口：新增 / 编辑 / 删除 / 启用·暂停。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from core.scheduler import next_trigger_after
from core.version import APP_VERSION

COLUMNS = ("title", "content", "rule", "state")
HEADINGS = {"title": "标题", "content": "内容", "rule": "规则", "state": "状态"}
WIDTHS = {"title": 195, "content": 210, "rule": 225, "state": 75}


class MainWindow:
    def __init__(self, root: tk.Tk, app) -> None:
        self.root = root
        self.app = app

        root.title(f"提醒钟 {APP_VERSION}")
        root.geometry("800x470")
        root.minsize(640, 360)

        outer = ttk.Frame(root, padding=10)
        outer.pack(fill="both", expand=True)

        # 工具栏
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="＋ 新增", width=10,
                   command=self.app.open_add).pack(side="left", padx=(0, 6))
        self.btn_edit = ttk.Button(bar, text="编辑", width=8,
                                   command=self._on_edit, state="disabled")
        self.btn_edit.pack(side="left", padx=(0, 6))
        self.btn_toggle = ttk.Button(bar, text="启用 / 暂停", width=12,
                                     command=self._on_toggle,
                                     state="disabled")
        self.btn_toggle.pack(side="left", padx=(0, 6))
        self.btn_del = ttk.Button(bar, text="删除", width=8,
                                  command=self._on_delete, state="disabled")
        self.btn_del.pack(side="left", padx=(0, 6))

        # 列表
        wrap = ttk.Frame(outer)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=COLUMNS, show="headings",
                                 selectmode="browse")
        for col in COLUMNS:
            self.tree.heading(col, text=HEADINGS[col])
            self.tree.column(col, width=WIDTHS[col], anchor="w",
                             stretch=(col != "state"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("normal", foreground="#222222")
        self.tree.tag_configure("paused", foreground="#b45309")
        self.tree.tag_configure("expired", foreground="#9ca3af")
        self.tree.tag_configure("broken", foreground="#dc2626")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double)

        ttk.Label(outer, foreground="#999999", text=(
            "提示：点右上角 × 会隐藏到后台（托盘图标仍在）；"
            "需要彻底退出时请用托盘菜单的“退出”。"
        )).pack(anchor="w", pady=(8, 0))

        self.refresh()

    # ---------- 数据刷新 ----------
    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        now = datetime.now()
        items = list(self.app.reminders)
        for r in items:
            tag = self._state_tag(r, now)
            self.tree.insert("", "end", iid=r.id,
                             values=(r.title, r.content or "",
                                     r.rule_text(), r.state_text(now)),
                             tags=(tag,))
        self._on_select()

    @staticmethod
    def _state_tag(r, now: datetime) -> str:
        if not r.enabled:
            return "paused"
        if r.rule == "once" and r.state_text(now) == "已过期":
            return "expired"
        try:
            if r.enabled and r.rule != "once":
                nxt = next_trigger_after(r, now)
                if nxt is None:
                    return "broken"
        except ValueError:
            return "broken"
        return "normal"

    # ---------- 选择状态 ----------
    def _selected_id(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_select(self, *_args) -> None:
        state = "normal" if self._selected_id() else "disabled"
        self.btn_edit.configure(state=state)
        self.btn_toggle.configure(state=state)
        self.btn_del.configure(state=state)

    # ---------- 操作 ----------
    def _on_double(self, _event) -> None:
        if self._selected_id():
            self._on_edit()

    def _on_edit(self) -> None:
        rid = self._selected_id()
        if rid:
            self.app.open_edit(rid)

    def _on_delete(self) -> None:
        rid = self._selected_id()
        if not rid:
            return
        r = self.app.find(rid)
        label = (r.title or "（无标题）") if r else rid
        if messagebox.askokcancel("删除提醒", f"确定删除“{label}”吗？",
                                  parent=self.root):
            self.app.delete_reminder(rid)

    def _on_toggle(self) -> None:
        rid = self._selected_id()
        if rid:
            self.app.toggle_enabled(rid)
