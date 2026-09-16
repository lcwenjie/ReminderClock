"""置顶提醒弹窗：必须点“知道了”才关闭；也可选“稍后提醒”，延迟分钟数可改。"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox

from core.models import SNOOZE_MAX, SNOOZE_MIN, Reminder


class AlertDialog(tk.Toplevel):
    """到点提醒弹窗。

    on_known 为无参回调；on_snooze 接收延迟分钟数。
    二者均在窗口销毁后由控制器调用。
    """

    def __init__(self, master: tk.Misc, reminder: Reminder, fired_text: str,
                 on_known: Callable[[], None],
                 on_snooze: Callable[[int], None]) -> None:
        super().__init__(master)
        self.reminder_id = reminder.id
        self._on_known = on_known
        self._on_snooze = on_snooze

        self.title("提醒")
        self.resizable(False, False)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.configure(padx=18, pady=14, bg="#ffffff")

        # 标题
        tk.Label(self, text="⏰ 时间到", font=("Microsoft YaHei UI", 11, "bold"),
                 fg="#2563eb", bg="#ffffff").pack(anchor="w")

        # 提醒内容
        tk.Label(self, text=reminder.title or "（无标题提醒）",
                 font=("Microsoft YaHei UI", 15, "bold"),
                 fg="#111111", bg="#ffffff",
                 wraplength=400, justify="left").pack(anchor="w", pady=(8, 2))

        body = reminder.content or "该起身活动一下啦。"
        tk.Label(self, text=body, font=("Microsoft YaHei UI", 11),
                 fg="#333333", bg="#ffffff", wraplength=400,
                 justify="left").pack(anchor="w", pady=(0, 8))

        tk.Label(self, text=fired_text, font=("Microsoft YaHei UI", 9),
                 fg="#888888", bg="#ffffff").pack(anchor="w")

        # 按钮行：知道了 / 稍后提醒（延迟分钟数可改，默认取任务里的设置）
        btns = tk.Frame(self, bg="#ffffff")
        btns.pack(anchor="e", pady=(14, 0))
        tk.Button(btns, text="知道了", width=10, command=self._known,
                  font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 14))
        tk.Label(btns, text="延后", font=("Microsoft YaHei UI", 10),
                 fg="#333333", bg="#ffffff").pack(side="left")
        self.snooze_var = tk.StringVar(value=str(reminder.snooze_minutes))
        tk.Spinbox(btns, from_=SNOOZE_MIN, to=SNOOZE_MAX, width=5,
                   textvariable=self.snooze_var, justify="center",
                   font=("Microsoft YaHei UI", 10)).pack(side="left", padx=4)
        tk.Label(btns, text="分钟", font=("Microsoft YaHei UI", 10),
                 fg="#333333", bg="#ffffff").pack(side="left", padx=(0, 8))
        tk.Button(btns, text="稍后提醒", width=10, command=self._snooze,
                  font=("Microsoft YaHei UI", 10)).pack(side="left")

        # 关闭窗口等价于“知道了”；Esc 同理
        self.protocol("WM_DELETE_WINDOW", self._known)
        self.bind("<Escape>", lambda e: self._known())

        self._center_on(master)
        self.after(150, self._raise_above)

    # ---------- 内部 ----------
    def _center_on(self, master: tk.Misc) -> None:
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        try:
            x = master.winfo_rootx() + (master.winfo_width() - w) // 2
            y = master.winfo_rooty() + (master.winfo_height() - h) // 2
        except tk.TclError:
            x = y = 0
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = min(max(x, 0), sw - w)
        y = min(max(y, 0), sh - h)
        self.geometry(f"+{x}+{y}")

    def _raise_above(self) -> None:
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.focus_force()
        except tk.TclError:
            pass

    def _known(self) -> None:
        self.destroy()
        self._on_known()

    def _snooze(self) -> None:
        raw = self.snooze_var.get().strip()
        try:
            minutes = int(raw)
        except ValueError:
            messagebox.showwarning("提醒", "延迟时间请输入整数分钟。", parent=self)
            return
        if not (SNOOZE_MIN <= minutes <= SNOOZE_MAX):
            messagebox.showwarning(
                "提醒", f"延迟时间需在 {SNOOZE_MIN}-{SNOOZE_MAX} 分钟之间。",
                parent=self)
            return
        self.destroy()
        self._on_snooze(minutes)

    def destroy_now(self) -> None:
        """由控制器主动关闭（例如该提醒被删除/暂停）。"""
        try:
            self.destroy()
        except tk.TclError:
            pass
