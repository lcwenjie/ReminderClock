"""提醒钟 —— 带系统托盘的提醒程序入口。

运行：  pip install pystray pillow
        python main.py        （想无控制台窗口运行可用 pythonw main.py）

说明：本文件作为控制器把所有模块装配起来：
- 主线程跑 tkinter（所有 UI/调度都在这里）
- pystray 托盘运行在独立线程，回调通过线程安全队列 post() 扔回主线程
- 调度器每 1 秒轮询一次，到点弹置顶提醒窗
"""
from __future__ import annotations

import queue
import sys
import tkinter as tk
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from types import TracebackType
from typing import cast

from core.models import Reminder, app_dir, load_reminders, save_reminders
from core.scheduler import Scheduler
from gui.alert import AlertDialog
from gui.form import ask_reminder
from gui.main_window import MainWindow
from gui.tray import TrayIcon, create_tray

#: 异常信息三元组，与 sys.exc_info() 及 tkinter 回调异常形参一致
ExcInfo = tuple[type[BaseException] | None, BaseException | None, TracebackType | None]


def _error_log_path() -> Path:
    """错误日志写在程序（exe）同一文件夹，方便拷贝给开发者排查。"""
    try:
        return app_dir() / "error.log"
    except Exception:
        return Path.home() / "ReminderClock_error.log"


def _log_error(source: str, exc_info: ExcInfo) -> None:
    """把异常堆栈追加写入日志文件。"""
    try:
        with _error_log_path().open("a", encoding="utf-8") as fh:
            _ = fh.write(
                f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] [{source}] 异常：\n")
            traceback.print_exception(*exc_info, file=fh)
    except Exception:
        pass


class ReminderApp:
    def __init__(self, data_path: Path | str | None = None) -> None:
        self.data_path: Path | str | None = data_path
        self.reminders: list[Reminder] = load_reminders(data_path)

        self._cmdq: queue.Queue[Callable[[], None]] = queue.Queue()
        self._quitting: bool = False
        self._snooze_timers: dict[str, str] = {}
        self._alerts: dict[str, AlertDialog] = {}
        self.icon: TrayIcon | None = None

        self.root: tk.Tk = tk.Tk()
        self.root.option_add("*Font", ("Microsoft YaHei UI", 9))  # pyright: ignore[reportUnknownMemberType]  # tkinter 部分接口无完整类型标注
        self.root.protocol("WM_DELETE_WINDOW", self.hide_main)
        # 界面回调（按钮/轮询等）一旦异常就记日志 + 提示，避免程序"假死"
        self.root.report_callback_exception = self._on_cb_error

        self.scheduler: Scheduler = Scheduler()
        self.scheduler.sync(self.reminders, datetime.now())

        self.main: MainWindow = MainWindow(self.root, self)
        self.show_main()

    # ---------- 生命周期 ----------
    def run(self) -> None:
        try:
            tray = create_tray(self)
        except Exception as exc:  # 缺 pystray / Pillow 等
            _ = messagebox.showerror(
                "提醒钟",
                "无法启动托盘图标。\n\n请先安装依赖：\n"
                + "    pip install pystray pillow\n\n"
                + f"详细错误：{exc}")
            self.root.destroy()
            return
        self.icon = tray
        tray.run_detached()
        _ = self.root.after(1000, self._tick)
        self.root.mainloop()

    def _on_cb_error(self, *args: object) -> None:
        """tkinter 回调内的异常统一处理：写日志 + 提示 + 安全退出。"""
        exc_info = cast("ExcInfo", args if len(args) >= 3 else sys.exc_info())
        _log_error("界面回调", exc_info)
        try:
            _ = messagebox.showerror(
                "提醒钟",
                "程序内部出错了，为避免后台假死将自动退出。\n\n"
                + "请把以下日志文件发给开发者排查：\n"
                + str(_error_log_path()))
        except Exception:
            pass
        self.request_quit()

    def request_quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._persist()
        try:
            if self.icon is not None:
                self.icon.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---------- 主线程轮询（调度 + 执行来自托盘的指令） ----------
    def _tick(self) -> None:
        if self._quitting:
            return
        # 1) 执行从其他线程（托盘）排队过来的指令
        drained = 0
        while drained < 64:
            try:
                fn = self._cmdq.get_nowait()
            except queue.Empty:
                break
            fn()
            drained += 1
        if self._quitting:
            return
        # 2) 检查到点的提醒
        now = datetime.now()
        for r in self.scheduler.poll(self.reminders, now):
            self._fire(r)
        if not self._quitting:
            _ = self.root.after(1000, self._tick)

    def post(self, fn: Callable[[], None]) -> None:
        """其他线程安全地请求主线程执行 fn。"""
        self._cmdq.put(fn)

    # ---------- 提醒触发 ----------
    def _fire(self, r: Reminder) -> None:
        if r.id in self._alerts:  # 已有弹窗，不再重复开
            return
        fired_text = (f"计划时间：{r.rule_text()}\n"
                      f"当前时间：{datetime.now():%Y-%m-%d %H:%M}")
        dlg = AlertDialog(
            self.root, r, fired_text,
            on_known=lambda rid=r.id: self._on_known(rid),
            on_snooze=lambda minutes, rid=r.id: self._on_snooze(rid, minutes))
        self._alerts[r.id] = dlg

    def _on_known(self, rid: str) -> None:
        _ = self._alerts.pop(rid, None)
        self.cancel_snooze(rid)
        cur = self.find(rid)
        if cur is None:
            self.scheduler.release(rid)
            return
        if cur.rule == "once":
            # 单次提醒确认后自动移除
            self.scheduler.release(rid)
            self.reminders.remove(cur)
            self._persist()
            self.main.refresh()
        else:
            self.scheduler.ack(cur, datetime.now())

    def _on_snooze(self, rid: str, minutes: int) -> None:
        _ = self._alerts.pop(rid, None)
        cur = self.find(rid)
        if cur is None or not cur.enabled:
            self.scheduler.release(rid)
            return
        if minutes != cur.snooze_minutes:
            # 在提醒弹窗里改了延迟时间：同步回该任务的设置并保存
            cur.snooze_minutes = minutes
            self._persist()
        self.cancel_snooze(rid)
        timer = self.root.after(
            minutes * 60 * 1000,
            lambda: self._fire_after_snooze(rid))
        self._snooze_timers[rid] = timer

    def _fire_after_snooze(self, rid: str) -> None:
        _ = self._snooze_timers.pop(rid, None)
        cur = self.find(rid)
        if cur is None or not cur.enabled:
            self.scheduler.release(rid)
            return
        if not self.scheduler.is_pending(rid):  # 触发状态已被清掉则不再补弹
            self.scheduler.release(rid)
            return
        self._fire(cur)

    def cancel_snooze(self, rid: str) -> None:
        timer = self._snooze_timers.pop(rid, None)
        if timer is not None:
            try:
                self.root.after_cancel(timer)
            except Exception:
                pass

    def close_alerts_for(self, rid: str) -> None:
        dlg = self._alerts.pop(rid, None)
        if dlg is not None:
            dlg.destroy_now()

    # ---------- 增删改（由主窗口调用） ----------
    def find(self, rid: str) -> Reminder | None:
        for r in self.reminders:
            if r.id == rid:
                return r
        return None

    def open_add(self) -> None:
        self.show_main()
        res = ask_reminder(self.root, None)
        if res is not None:
            self._apply(res)

    def open_edit(self, rid: str) -> None:
        cur = self.find(rid)
        if cur is None:
            return
        res = ask_reminder(self.root, cur)
        if res is not None:
            self._apply(res)

    def delete_reminder(self, rid: str) -> None:
        self.close_alerts_for(rid)
        self.cancel_snooze(rid)
        self.scheduler.release(rid)
        cur = self.find(rid)
        if cur is not None:
            self.reminders.remove(cur)
        self._persist()
        self.main.refresh()

    def toggle_enabled(self, rid: str) -> None:
        cur = self.find(rid)
        if cur is None:
            return
        self.close_alerts_for(rid)
        self.cancel_snooze(rid)
        cur.enabled = not cur.enabled
        self.scheduler.release(rid)
        self.scheduler.reschedule(cur, datetime.now())
        self._persist()
        self.main.refresh()

    def _apply(self, r: Reminder) -> None:
        """新增（r.id 不在列表）或编辑（覆盖同 id 项）后统一收尾。"""
        self.close_alerts_for(r.id)
        self.cancel_snooze(r.id)
        self.scheduler.release(r.id)
        for i, item in enumerate(self.reminders):
            if item.id == r.id:
                self.reminders[i] = r
                break
        else:
            self.reminders.append(r)
        self.scheduler.reschedule(r, datetime.now())
        self._persist()
        self.main.refresh()

    # ---------- 主窗口显隐 ----------
    def show_main(self) -> None:
        self.root.deiconify()
        self.root.lift()  # pyright: ignore[reportUnknownMemberType]  # tkinter 部分接口无完整类型标注
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def hide_main(self) -> None:
        self.root.withdraw()

    # ---------- 持久化 ----------
    def _persist(self) -> None:
        try:
            save_reminders(self.reminders, self.data_path)
        except OSError as exc:
            _ = messagebox.showwarning("提醒钟", f"保存数据失败：{exc}",
                                       parent=self.root)


def main() -> None:
    try:
        app = ReminderApp()
        app.run()
    except SystemExit:
        raise
    except Exception:
        _log_error("启动/主流程", sys.exc_info())
        traceback.print_exc()  # 开发环境可直接看到；打包后控制台被隐藏，无影响
        try:
            _ = messagebox.showerror(
                "提醒钟",
                "程序启动失败。\n\n请把以下日志文件发给开发者排查：\n"
                + str(_error_log_path()))
        except Exception:
            pass
        raise SystemExit(1)


if __name__ == "__main__":
    main()
