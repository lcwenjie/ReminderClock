"""新增 / 编辑提醒的表单对话框。

用法：
    reminder = ask_reminder(root, existing)   # existing 为 None 表示新增
    # 返回新的 Reminder 对象；用户取消则返回 None。
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from core.models import (DEFAULT_INTERVAL_MINUTES, DEFAULT_SNOOZE_MINUTES,
                         DEFAULT_WINDOW_END, DEFAULT_WINDOW_START, INTERVAL_MAX,
                         INTERVAL_MIN, SNOOZE_MAX, SNOOZE_MIN, Reminder,
                         parse_date, parse_time)

FONT = "Microsoft YaHei UI"


def _default_when() -> datetime:
    """新增提醒时的默认时间：当前时间向上取整到下一分钟。

    时间输入只精确到分钟，若直接填“当前分钟”，单次提醒会因为触发时间不晚于
    当前时刻而无法提交，因此默认取下一分钟，保证新增后可直接确定。
    """
    return (datetime.now() + timedelta(minutes=1)).replace(second=0, microsecond=0)


class _FormDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, existing: Reminder | None) -> None:
        super().__init__(master)
        self.existing = existing
        self.result: Reminder | None = None

        self.title("新增提醒" if existing is None else "编辑提醒")
        self.resizable(False, False)
        try:
            self.transient(master)
        except tk.TclError:
            pass
        self.configure(padx=18, pady=14)

        # ---------- 变量 ----------
        default_when = _default_when()
        self.title_var = tk.StringVar(value=existing.title if existing else "")
        self.rule_var = tk.StringVar(value=existing.rule if existing else "once")
        self.date_var = tk.StringVar(
            value=(existing.date if existing and existing.rule == "once"
                   else default_when.date().isoformat()))
        self.time_var = tk.StringVar(
            value=existing.time if existing else default_when.strftime("%H:%M"))
        self.start_var = tk.StringVar(
            value=existing.start_time if existing else DEFAULT_WINDOW_START)
        self.end_var = tk.StringVar(
            value=existing.end_time if existing else DEFAULT_WINDOW_END)
        self.interval_var = tk.StringVar(
            value=str(existing.interval_minutes if existing
                      else DEFAULT_INTERVAL_MINUTES))
        # “时间段”是每天 / 每周下面的子选项：at=指定时间，span=时间段
        self.mode_var = tk.StringVar(
            value=("span" if existing and existing.span else "at"))
        self.enabled_var = tk.BooleanVar(
            value=existing.enabled if existing else True)
        self.snooze_var = tk.StringVar(
            value=str(existing.snooze_minutes if existing
                      else DEFAULT_SNOOZE_MINUTES))
        self.day_vars = [tk.BooleanVar(value=((i in (existing.weekdays or []))
                                              if existing else (i == 0)))
                         for i in range(7)]

        self._build()
        self._update_rule_state()

        # 模态：等窗口关闭
        self.grab_set()
        self._center_on(master)

    # ---------- 界面 ----------
    def _build(self) -> None:
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="标题 *").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.title_var, width=46).grid(
            row=0, column=1, sticky="we", padx=(6, 0), pady=3)

        ttk.Label(body, text="内容").grid(row=1, column=0, sticky="nw", pady=3)
        self.content_text = tk.Text(body, width=34, height=3,
                                    font=(FONT, 9))
        self.content_text.grid(row=1, column=1, sticky="we", padx=(6, 0), pady=3)
        if self.existing:
            self.content_text.insert("1.0", self.existing.content or "")

        ttk.Label(body, text="规则").grid(row=2, column=0, sticky="w", pady=3)
        rules = ttk.Frame(body)
        rules.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=3)
        for text, val in (("单次", "once"), ("每天", "daily"),
                          ("每周", "weekly")):
            ttk.Radiobutton(rules, text=text, value=val,
                            variable=self.rule_var,
                            command=self._update_rule_state).pack(side="left",
                                                                  padx=(0, 12))

        # 方式（每天 / 每周的子选项）：指定时间 或 时间段
        ttk.Label(body, text="方式").grid(row=3, column=0, sticky="w", pady=3)
        mode = ttk.Frame(body)
        mode.grid(row=3, column=1, sticky="w", padx=(6, 0), pady=3)
        self.mode_radios = []
        for text, val in (("指定时间", "at"), ("时间段", "span")):
            rb = ttk.Radiobutton(mode, text=text, value=val,
                                 variable=self.mode_var,
                                 command=self._update_rule_state)
            rb.pack(side="left", padx=(0, 12))
            self.mode_radios.append(rb)

        # 日期（仅单次）
        ttk.Label(body, text="日期 *").grid(row=4, column=0, sticky="w", pady=3)
        self.date_entry = ttk.Entry(body, textvariable=self.date_var, width=12)
        self.date_entry.grid(row=4, column=1, sticky="w", padx=(6, 0), pady=3)
        ttk.Label(body, text="格式 年-月-日，例如 2026-09-10",
                  foreground="#777777").grid(row=4, column=1, sticky="w",
                                             padx=(120, 0), pady=3)

        # 时间（指定时间模式：单次 / 每天 / 每周）
        ttk.Label(body, text="时间 *").grid(row=5, column=0, sticky="w", pady=3)
        self.time_entry = ttk.Entry(body, textvariable=self.time_var, width=8)
        self.time_entry.grid(row=5, column=1, sticky="w", padx=(6, 0), pady=3)
        self.time_hint = ttk.Label(body, text="格式 时:分，例如 09:30",
                                   foreground="#777777")
        self.time_hint.grid(row=5, column=1, sticky="w", padx=(90, 0), pady=3)

        # 时间段（每天 / 每周选“时间段”时）：开始 - 结束，每 N 分钟一次
        ttk.Label(body, text="时间段 *").grid(row=6, column=0, sticky="w", pady=3)
        span = ttk.Frame(body)
        span.grid(row=6, column=1, sticky="w", padx=(6, 0), pady=3)
        self.start_entry = ttk.Entry(span, textvariable=self.start_var, width=8)
        self.start_entry.pack(side="left")
        ttk.Label(span, text="至").pack(side="left", padx=4)
        self.end_entry = ttk.Entry(span, textvariable=self.end_var, width=8)
        self.end_entry.pack(side="left")
        ttk.Label(span, text="每").pack(side="left", padx=(10, 4))
        self.interval_entry = ttk.Entry(span, textvariable=self.interval_var,
                                        width=6)
        self.interval_entry.pack(side="left")
        ttk.Label(span, text="分钟一次", foreground="#777777").pack(
            side="left", padx=(4, 0))
        ttk.Label(body, text="开始时刻即首次执行时间；不跨天",
                  foreground="#777777").grid(row=6, column=1, sticky="w",
                                             padx=(300, 0), pady=3)

        # 星期（仅每周，指定时间与时间段两种模式都适用）
        ttk.Label(body, text="星期 *").grid(row=7, column=0, sticky="w", pady=3)
        days = ttk.Frame(body)
        days.grid(row=7, column=1, sticky="w", padx=(6, 0), pady=3)
        self.day_checks = []
        for i, name in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            cb = ttk.Checkbutton(days, text=name, variable=self.day_vars[i])
            cb.pack(side="left", padx=(0, 4))
            self.day_checks.append(cb)

        # 延迟提醒（到点后“稍后提醒”的默认间隔，可在提醒时再改）
        ttk.Label(body, text="延迟提醒").grid(row=8, column=0, sticky="w", pady=3)
        snooze = ttk.Frame(body)
        snooze.grid(row=8, column=1, sticky="w", padx=(6, 0), pady=3)
        ttk.Entry(snooze, textvariable=self.snooze_var, width=6).pack(side="left")
        ttk.Label(snooze, text=f"分钟（{SNOOZE_MIN}-{SNOOZE_MAX}，"
                               "到点后可点“稍后提醒”）",
                  foreground="#777777").pack(side="left", padx=(6, 0))

        # 启用
        ttk.Checkbutton(body, text="启用这条提醒",
                        variable=self.enabled_var).grid(
            row=9, column=1, sticky="w", padx=(6, 0), pady=(8, 4))

        # 按钮
        btns = ttk.Frame(body)
        btns.grid(row=10, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="确定", width=10, command=self._submit).pack(
            side="left", padx=(0, 8))
        ttk.Button(btns, text="取消", width=10,
                   command=self.destroy).pack(side="left")

    # ---------- 逻辑 ----------
    def _update_rule_state(self) -> None:
        rule = self.rule_var.get()
        once = rule == "once"
        # “时间段”只对每天 / 每周有效；单次固定用指定时间
        span = (not once) and self.mode_var.get() == "span"
        self.date_entry.configure(state="normal" if once else "disabled")
        self.time_entry.configure(state="disabled" if span else "normal")
        for rb in self.mode_radios:
            rb.configure(state="disabled" if once else "normal")
        for cb in self.day_checks:
            cb.configure(state="normal" if rule == "weekly" else "disabled")
        for entry in (self.start_entry, self.end_entry, self.interval_entry):
            entry.configure(state="normal" if span else "disabled")

    def _submit(self) -> None:
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("提示", "请填写标题。", parent=self)
            return

        rule = self.rule_var.get()
        # “时间段”是每天 / 每周下面的子选项
        span = rule in ("daily", "weekly") and self.mode_var.get() == "span"
        time_val = self.time_var.get().strip()
        start_val = self.start_var.get().strip()
        end_val = self.end_var.get().strip()
        interval = DEFAULT_INTERVAL_MINUTES
        if span:
            try:
                sh, sm = parse_time(start_val)
                eh, em = parse_time(end_val)
            except ValueError:
                messagebox.showwarning("提示", "时间段格式不正确，应为 HH:MM，"
                                       "如 08:00 至 17:30。", parent=self)
                return
            if eh * 60 + em <= sh * 60 + sm:
                messagebox.showwarning("提示", "结束时间必须晚于开始时间"
                                       "（暂不支持跨天时间段）。", parent=self)
                return
            try:
                interval = int(self.interval_var.get().strip())
            except ValueError:
                messagebox.showwarning("提示", "间隔请输入整数分钟，如 30。",
                                       parent=self)
                return
            if not (INTERVAL_MIN <= interval <= INTERVAL_MAX):
                messagebox.showwarning(
                    "提示", f"间隔需在 {INTERVAL_MIN}-{INTERVAL_MAX} 分钟之间。",
                    parent=self)
                return
            time_val = start_val  # 时间段模式的 time 与开始时刻保持一致
        else:
            try:
                parse_time(time_val)
            except ValueError:
                messagebox.showwarning("提示", "时间格式不正确，应为 HH:MM，"
                                       "如 09:30。", parent=self)
                return

        date_val = ""
        weekdays: list[int] = []
        if rule == "once":
            date_val = self.date_var.get().strip()
            try:
                d = parse_date(date_val)
                when = datetime(d.year, d.month, d.day,
                                *parse_time(time_val))
            except ValueError:
                messagebox.showwarning("提示", "日期格式不正确，应为 "
                                       "YYYY-MM-DD，如 2026-09-10。",
                                       parent=self)
                return
            if when <= datetime.now():
                messagebox.showwarning("提示", "单次提醒的时间必须晚于当前时间。",
                                       parent=self)
                return
        elif rule == "weekly":
            weekdays = [i for i, v in enumerate(self.day_vars) if v.get()]
            if not weekdays:
                messagebox.showwarning("提示", "请至少勾选一个星期。",
                                       parent=self)
                return

        try:
            snooze = int(self.snooze_var.get().strip())
        except ValueError:
            messagebox.showwarning("提示", "延迟提醒时间请输入整数分钟，如 5。",
                                   parent=self)
            return
        if not (SNOOZE_MIN <= snooze <= SNOOZE_MAX):
            messagebox.showwarning(
                "提示", f"延迟提醒时间需在 {SNOOZE_MIN}-{SNOOZE_MAX} 分钟之间。",
                parent=self)
            return

        content = self.content_text.get("1.0", "end-1c").strip()
        r = Reminder(title=title, content=content, rule=rule, span=span,
                     date=date_val, time=time_val, weekdays=weekdays,
                     start_time=start_val, end_time=end_val,
                     interval_minutes=interval,
                     enabled=self.enabled_var.get(), snooze_minutes=snooze)
        if self.existing:
            r.id = self.existing.id
            r.created_at = self.existing.created_at
        self.result = r
        self.destroy()

    def _center_on(self, master: tk.Tk) -> None:
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        try:
            x = master.winfo_rootx() + (master.winfo_width() - w) // 2
            y = master.winfo_rooty() + (master.winfo_height() - h) // 2
        except tk.TclError:
            x, y = 0, 0
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = min(max(x, 0), max(sw - w, 0))
        y = min(max(y, 0), max(sh - h, 0))
        self.geometry(f"+{x}+{y}")


def ask_reminder(master: tk.Tk, existing: Reminder | None) -> Reminder | None:
    """弹出新增/编辑表单，阻塞至窗口关闭。"""
    dlg = _FormDialog(master, existing)
    master.wait_window(dlg)
    return dlg.result
