"""调度逻辑单元测试。

可两种方式运行：
    1) python tests/test_scheduler.py      （无第三方依赖，直接跑）
    2) python -m pytest tests/             （如有 pytest）
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import Reminder  # noqa: E402
from core.scheduler import Scheduler, next_trigger_after  # noqa: E402


def make(**kw) -> Reminder:
    defaults = dict(rule="daily", time="09:00")
    defaults.update(kw)
    return Reminder(**defaults)


# 固定的“当前时刻”：2026-09-09 是周三
WED_0800 = datetime(2026, 9, 9, 8, 0, 0)
WED_0900 = datetime(2026, 9, 9, 9, 0, 0)
WED_1000 = datetime(2026, 9, 9, 10, 0, 0)


# ---------------- 单次 ----------------
def test_once_future_returns_its_time():
    r = make(rule="once", date="2026-09-10", time="09:00")
    assert next_trigger_after(r, WED_0800) == datetime(2026, 9, 10, 9, 0)


def test_once_at_same_moment_is_not_next():
    """到点的那一刻应视为“本次已到期”，不返回做未来登记。"""
    r = make(rule="once", date="2026-09-09", time="09:00")
    assert next_trigger_after(r, WED_0900) is None


def test_once_expired_returns_none():
    r = make(rule="once", date="2026-09-08", time="23:00")
    assert next_trigger_after(r, WED_0800) is None


# ---------------- 每天 ----------------
def test_daily_before_time_same_day():
    r = make(rule="daily", time="09:00")
    assert next_trigger_after(r, WED_0800) == WED_0900


def test_daily_after_time_next_day():
    r = make(rule="daily", time="09:00")
    assert next_trigger_after(r, WED_1000) == datetime(2026, 9, 10, 9, 0)


def test_daily_at_same_second_counts_as_passed():
    r = make(rule="daily", time="09:00")
    assert next_trigger_after(r, WED_0900) == datetime(2026, 9, 10, 9, 0)


# ---------------- 每周 ----------------
def test_weekly_finds_next_selected_weekday():
    r = make(rule="weekly", time="09:00", weekdays=[4])  # 周五
    assert next_trigger_after(r, WED_0800) == datetime(2026, 9, 11, 9, 0)


def test_weekly_same_weekday_past_time_goes_to_next_week():
    r = make(rule="weekly", time="08:00", weekdays=[2])  # 周三
    assert next_trigger_after(r, WED_1000) == datetime(2026, 9, 16, 8, 0)


def test_weekly_today_is_next_when_still_future():
    r = make(rule="weekly", time="09:00", weekdays=[2])  # 周三
    assert next_trigger_after(r, WED_0800) == WED_0900


def test_weekly_empty_days_returns_none():
    r = make(rule="weekly", time="09:00", weekdays=[])
    assert next_trigger_after(r, WED_0800) is None


# ---------------- 时间段（span：每天 / 每周下的子选项） ----------------
WINDOW = dict(rule="daily", span=True, start_time="08:00", end_time="17:30",
              interval_minutes=30)


def test_span_before_start_returns_today_start():
    r = make(**WINDOW)
    assert next_trigger_after(r, datetime(2026, 9, 9, 7, 59)) == WED_0800


def test_span_at_start_moment_goes_to_next_slot():
    """到点那一刻视为“本次已到期”，返回下一个网格点。"""
    r = make(**WINDOW)
    assert next_trigger_after(r, WED_0800) == datetime(2026, 9, 9, 8, 30)


def test_span_between_slots_rounds_up():
    r = make(**WINDOW)
    assert next_trigger_after(r, datetime(2026, 9, 9, 9, 10)) == \
        datetime(2026, 9, 9, 9, 30)


def test_span_end_is_inclusive_then_next_day():
    r = make(**WINDOW)
    assert next_trigger_after(r, datetime(2026, 9, 9, 17, 29)) == \
        datetime(2026, 9, 9, 17, 30)
    assert next_trigger_after(r, datetime(2026, 9, 9, 17, 30)) == \
        datetime(2026, 9, 10, 8, 0)


def test_span_after_window_returns_next_day_start():
    r = make(**WINDOW)
    assert next_trigger_after(r, datetime(2026, 9, 9, 22, 0)) == \
        datetime(2026, 9, 10, 8, 0)


def test_span_step_not_dividing_window():
    """45 分钟一档：08:00-09:30 只有 08:00 / 08:45 / 09:30 三档。"""
    r = make(rule="daily", span=True, start_time="08:00", end_time="09:30",
             interval_minutes=45)
    assert next_trigger_after(r, datetime(2026, 9, 9, 8, 10)) == \
        datetime(2026, 9, 9, 8, 45)
    assert next_trigger_after(r, datetime(2026, 9, 9, 9, 0)) == \
        datetime(2026, 9, 9, 9, 30)
    assert next_trigger_after(r, datetime(2026, 9, 9, 9, 31)) == \
        datetime(2026, 9, 10, 8, 0)


def test_span_invalid_window_returns_none():
    r = make(rule="daily", span=True, start_time="18:00", end_time="08:00",
             interval_minutes=30)
    assert next_trigger_after(r, WED_0800) is None
    assert r.window_valid() is False
    assert r.state_text(WED_0800) == "配置错误"


def test_span_weekly_only_on_selected_days():
    r = make(rule="weekly", span=True, start_time="08:00", end_time="17:30",
             interval_minutes=30, weekdays=[2])          # 仅周三
    assert next_trigger_after(r, datetime(2026, 9, 9, 7, 30)) == WED_0800
    # 当天时段结束 → 下一个周三
    assert next_trigger_after(r, datetime(2026, 9, 9, 17, 31)) == \
        datetime(2026, 9, 16, 8, 0)
    # 周四不在范围内 → 下周三
    assert next_trigger_after(r, datetime(2026, 9, 10, 9, 0)) == \
        datetime(2026, 9, 16, 8, 0)


def test_span_weekly_multi_days():
    r = make(rule="weekly", span=True, start_time="09:00", end_time="12:00",
             interval_minutes=60, weekdays=[0, 4])       # 周一、周五
    assert next_trigger_after(r, WED_1000) == datetime(2026, 9, 11, 9, 0)
    assert next_trigger_after(r, datetime(2026, 9, 11, 9, 0)) == \
        datetime(2026, 9, 11, 10, 0)


def test_span_daily_ignores_weekdays():
    """每天 + 时间段：星期不生效（会被清空）。"""
    r = make(rule="daily", span=True, start_time="09:00", end_time="10:00",
             interval_minutes=30, weekdays=[2])
    assert r.weekdays == []
    # 2026-09-10 是周四，仍然执行
    assert next_trigger_after(r, datetime(2026, 9, 10, 8, 0)) == \
        datetime(2026, 9, 10, 9, 0)


def test_span_rule_text():
    assert make(**WINDOW).rule_text() == "每天 08:00-17:30 每30分钟"
    r = make(rule="weekly", span=True, start_time="08:00", end_time="17:30",
             interval_minutes=30, weekdays=[0, 2])
    assert r.rule_text() == "每周一、三 08:00-17:30 每30分钟"


def test_span_roundtrip():
    r = make(rule="weekly", span=True, start_time="08:00", end_time="17:30",
             interval_minutes=30, weekdays=[2])
    again = Reminder.from_dict(r.to_dict())
    assert (again.rule, again.span) == ("weekly", True)
    assert (again.start_time, again.end_time, again.interval_minutes) == \
        ("08:00", "17:30", 30)
    assert again.weekdays == [2]     # 每周的星期限定也会被保存


def test_legacy_interval_rule_migrates_to_span():
    """旧数据里独立的 interval 规则：有星期→每周，无星期→每天。"""
    daily = Reminder.from_dict({"rule": "interval", "start_time": "08:00",
                                "end_time": "17:30", "interval_minutes": 30})
    assert (daily.rule, daily.span) == ("daily", True)
    weekly = Reminder.from_dict({"rule": "interval", "start_time": "08:00",
                                 "end_time": "17:30", "interval_minutes": 30,
                                 "weekdays": [2]})
    assert (weekly.rule, weekly.span) == ("weekly", True)
    assert weekly.weekdays == [2]


def test_span_scheduler_ack_reschedules_next_slot():
    s = Scheduler()
    r = make(**WINDOW)
    s.sync([r], datetime(2026, 9, 9, 7, 0))
    assert s.poll([r], WED_0800) == [r]
    assert s.poll([r], datetime(2026, 9, 9, 8, 10)) == []  # 等待确认期间不重复
    s.ack(r, datetime(2026, 9, 9, 8, 10))
    assert s.poll([r], datetime(2026, 9, 9, 8, 20)) == []
    assert s.poll([r], datetime(2026, 9, 9, 8, 30)) == [r]


# ---------------- 调度器状态机 ----------------
def test_scheduler_fires_once_then_waits_ack_then_reschedules():
    s = Scheduler()
    r = make(rule="daily", time="09:00")
    s.sync([r], WED_0800)

    assert s.poll([r], datetime(2026, 9, 9, 8, 59, 59)) == []
    due = s.poll([r], WED_0900)
    assert due == [r]
    # 确认前不会重复触发
    assert s.poll([r], datetime(2026, 9, 9, 9, 0, 30)) == []

    s.ack(r, datetime(2026, 9, 9, 9, 0, 30))
    # 下一次应为明天 9:00，今天不再触发
    assert s.poll([r], datetime(2026, 9, 9, 23, 59, 59)) == []
    assert s.poll([r], datetime(2026, 9, 10, 9, 0, 0)) == [r]


def test_scheduler_ignores_disabled_and_sync_clears_removed():
    s = Scheduler()
    a = make(rule="daily", time="09:00")
    b = make(rule="daily", time="09:00", enabled=False)
    s.sync([a, b], WED_0800)
    assert s.poll([a, b], WED_0900) == [a]

    s.sync([a], WED_1000)  # b 已从数据中删除
    assert s.poll([a], WED_1000) == []


def test_snooze_pending_blocks_duplicate_fire():
    """暂缓期间 scheduler 不重复触发（由控制器负责到时再次弹窗）。"""
    s = Scheduler()
    r = make(rule="daily", time="09:00")
    s.sync([r], WED_0800)
    assert s.poll([r], WED_0900) == [r]           # 触发一次（pending）
    assert s.poll([r], datetime(2026, 9, 9, 9, 5, 0)) == []  # 暂缓中不重复
    s.ack(r, datetime(2026, 9, 9, 9, 6, 0))      # 最终确认
    assert s.poll([r], datetime(2026, 9, 10, 9, 0)) == [r]


if __name__ == "__main__":
    tests = [
        (name, obj) for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(1 if failures else 0)
