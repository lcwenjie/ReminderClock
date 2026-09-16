"""提醒调度：计算“下次触发时间”、轮询判断到点。

语义约定：
- “下次触发时间”总是严格晚于 now，用于提前登记；“时间段”模式（span，每天/
  每周下的子选项）则是锚定 start 的间隔网格上严格晚于 now 的第一个点，且不晚
  于 end（start 即首次执行时间；每天执行或只在每周选中的几天执行）；
- 轮询时一旦 now >= 已登记的下次触发时间，即触发一次，并把该提醒标记为
  “待确认(pending)”，在用户点“知道了”之前不会重复触发；
- 点“知道了”后调用 ack()，按当前时间重新登记下一次触发（单次规则没有下次，
  由调用方负责删除）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .models import Reminder, parse_time


def _at(day: date, minutes: int) -> datetime:
    """某一天 + “从 0 点算起的分钟数” → datetime。"""
    return datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)


def _next_span(reminder: Reminder, now: datetime) -> datetime | None:
    """时间段模式：在 [start, end] 内按“锚定 start 的间隔网格”取下一个时刻。

    - start 即当日首次执行时间，之后按 interval 递进，且包含 end
      （如 08:00-17:30 / 每 30 分钟 → …、17:00、17:30）；
    - rule == "weekly" 时只在选中的星期几执行，rule == "daily" 时每天执行；
    - 今天时段已过（或今天不是执行日）则顺延到下一个执行日的 start；
    - end < start（跨天）视为配置错误。
    """
    try:
        sh, sm = parse_time(reminder.start_time)
        eh, em = parse_time(reminder.end_time)
    except ValueError:
        return None

    step = reminder.interval_minutes
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if step < 1 or end_min < start_min:
        return None

    days = ({d for d in reminder.weekdays if 0 <= d <= 6}
            if reminder.rule == "weekly" else set())
    allowed = days.__contains__

    day = now.date()
    if not days or allowed(day.weekday()):
        now_min = now.hour * 60 + now.minute
        if now_min < start_min:              # 今天时段还没开始
            return _at(day, start_min)
        # 已过 start：取严格晚于当前分钟的第一个网格点
        slot = start_min + ((now_min - start_min) // step + 1) * step
        if slot <= end_min:
            return _at(day, slot)

    for _ in range(8):  # 今天没机会了：顺延到下一个执行日的开始时刻
        day = day + timedelta(days=1)
        if not days or allowed(day.weekday()):
            return _at(day, start_min)
    return None


def next_trigger_after(reminder: Reminder, now: datetime) -> datetime | None:
    """返回该提醒在 now 之后的下一次触发时间；单次已过期则返回 None。"""
    if not reminder.enabled:
        return None

    if reminder.rule == "once":
        when = reminder.once_datetime()
        return when if when > now else None

    if reminder.span and reminder.rule in ("daily", "weekly"):
        return _next_span(reminder, now)

    hh, mm = parse_time(reminder.time)

    if reminder.rule == "daily":
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate > now:
            return candidate
        return candidate + timedelta(days=1)

    if reminder.rule == "weekly":
        days = set(reminder.weekdays)
        if not days:
            return None
        for i in range(0, 8):  # 从今天起最多找 7 天，必然命中一个已选星期
            day = (now + timedelta(days=i)).date()
            if day.weekday() not in days:
                continue
            cand = datetime(day.year, day.month, day.day, hh, mm)
            if cand > now:  # 严格晚于 now：今天已过点则自动顺延
                return cand
        return None

    raise ValueError(f"未知规则: {reminder.rule}")


class Scheduler:
    """维护每条提醒的下次触发登记，并输出“此刻到点”的提醒。"""

    def __init__(self) -> None:
        #: id -> 已登记的下次触发时间（可能为 None）
        self._next: dict[str, datetime | None] = {}
        #: 正处于“弹窗/暂缓、等待确认”状态的 id 集合
        self._pending: set[str] = set()

    def sync(self, reminders: list[Reminder], now: datetime) -> None:
        """全量重算登记（加载数据、批量变更后调用）。"""
        ids = {r.id for r in reminders}
        self._pending &= ids
        self._next = {r.id: next_trigger_after(r, now) for r in reminders}

    def reschedule(self, reminder: Reminder, now: datetime) -> None:
        """单条重算（新增/编辑后调用）。"""
        self._next[reminder.id] = next_trigger_after(reminder, now)

    def next_for(self, reminder: Reminder, now: datetime) -> datetime | None:
        """供 UI 排序/展示使用，不改变状态。"""
        return next_trigger_after(reminder, now)

    def poll(self, reminders: list[Reminder], now: datetime) -> list[Reminder]:
        """返回此刻到点、需要弹窗提醒的提醒列表；将其标记为 pending。"""
        due: list[Reminder] = []
        for r in reminders:
            if not r.enabled or r.id in self._pending:
                continue
            target = self._next.get(r.id)
            if target is None:
                continue
            if now >= target:
                self._pending.add(r.id)
                due.append(r)
        return due

    def ack(self, reminder: Reminder, now: datetime) -> None:
        """用户确认“知道了”：解除 pending，并登记下一次触发。"""
        self._pending.discard(reminder.id)
        self._next[reminder.id] = next_trigger_after(reminder, now)

    def release(self, reminder_id: str) -> None:
        """解除 pending 但不重新登记（删除或编辑该提醒时调用）。"""
        self._pending.discard(reminder_id)
        self._next.pop(reminder_id, None)

    def is_pending(self, reminder_id: str) -> bool:
        return reminder_id in self._pending
