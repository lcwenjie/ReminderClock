"""提醒数据模型与 JSON 持久化。

时间字段约定：
- rule : once（单次）| daily（每天）| weekly（每周）
- span : “时间段”模式开关——它是“每天 / 每周”下面的子选项，不是独立规则：
  * True  → 在 [start_time, end_time] 内每 interval_minutes 分钟提醒一次，
            start_time 即首次执行时间，两个端点时刻都会提醒，不支持跨天
            （end_time 需不早于 start_time）；
  * False → 在 time 指定的时刻提醒（每天一次 / 每周每选中的一天一次）。
  旧数据里独立的 rule == "interval" 会在加载时自动并入 daily/weekly + span=True
- date : "YYYY-MM-DD"，仅 rule == "once" 使用
- time : "HH:MM"，指定时间模式的触发时刻（span 模式下与 start_time 相同）
- weekdays : [0..6] 表示周一..周日，仅 rule == "weekly" 使用
- start_time / end_time / interval_minutes ：仅 span 模式使用
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import cast

#: 周一=0 .. 周日=6（与 datetime.weekday() 一致）
WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]
RULES_TEXT = {"once": "单次", "daily": "每天", "weekly": "每周"}

#: “稍后提醒”（延迟提醒）的默认分钟数与允许范围
DEFAULT_SNOOZE_MINUTES = 5
SNOOZE_MIN = 1
SNOOZE_MAX = 1440

#: “时间段”模式（span）的默认起止时刻与间隔，以及间隔允许范围（分钟）
DEFAULT_WINDOW_START = "09:00"
DEFAULT_WINDOW_END = "18:00"
DEFAULT_INTERVAL_MINUTES = 30
INTERVAL_MIN = 1
INTERVAL_MAX = 1440


def parse_time(value: str) -> tuple[int, int]:
    """解析 "HH:MM"，非法时抛 ValueError。"""
    hh, mm = (int(x) for x in value.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("时间必须在 00:00-23:59 之间")
    return hh, mm


def parse_date(value: str) -> date:
    """解析 "YYYY-MM-DD"，非法时抛 ValueError，返回 date 对象。"""
    return datetime.strptime(value, "%Y-%m-%d").date()


def weekday_text(weekdays: list[int]) -> str:
    """把 [0,2,4] 转成中文星期描述。"""
    names = [WEEKDAY_NAMES[i] for i in sorted(set(weekdays))]
    return "、".join(names) if names else "（未选择）"


def _as_bool(value: object, default: bool = True) -> bool:
    """把 JSON 里的启用标记稳健地转成 bool（兼容手写文件里的字符串/数字）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off", "n")
    return default


def _as_int(value: object, default: int) -> int:
    """把 JSON 里的整数稳健地转成 int（兼容手写文件里的字符串/浮点）。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_time_text(value: object, default: str) -> str:
    """把 JSON 里的 "HH:MM" 文本稳健地转过来；不是合法时间则回落默认值。"""
    if isinstance(value, str):
        try:
            parse_time(value)
            return value
        except ValueError:
            pass
    return default


@dataclass
class Reminder:
    id: str = ""
    title: str = ""
    content: str = ""
    rule: str = "once"          # once | daily | weekly
    #: “时间段”模式：每天/每周下的子选项（True 时按 start~end 每隔 N 分钟提醒）
    span: bool = False
    date: str = ""              # once 用：YYYY-MM-DD
    time: str = "09:00"         # HH:MM（span 模式下与 start_time 一致）
    weekdays: list[int] = field(default_factory=list)
    start_time: str = DEFAULT_WINDOW_START  # span 用：时段开始 HH:MM
    end_time: str = DEFAULT_WINDOW_END      # span 用：时段结束 HH:MM（含）
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES  # span 用：间隔分钟
    enabled: bool = True
    snooze_minutes: int = DEFAULT_SNOOZE_MINUTES  # 到点后“稍后提醒”的延迟（分钟）
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        # 旧版把“时段”当作独立规则：有星期→每周，无星期→每天，并打开 span
        if self.rule == "interval":
            self.rule = "weekly" if self.weekdays else "daily"
            self.span = True
        if self.rule != "weekly":
            self.weekdays = []
        self.span = _as_bool(self.span, False)
        self.start_time = _as_time_text(self.start_time, DEFAULT_WINDOW_START)
        self.end_time = _as_time_text(self.end_time, DEFAULT_WINDOW_END)
        try:
            self.interval_minutes = min(max(int(self.interval_minutes),
                                            INTERVAL_MIN), INTERVAL_MAX)
        except (TypeError, ValueError):
            self.interval_minutes = DEFAULT_INTERVAL_MINUTES
        try:
            self.snooze_minutes = min(max(int(self.snooze_minutes),
                                          SNOOZE_MIN), SNOOZE_MAX)
        except (TypeError, ValueError):
            self.snooze_minutes = DEFAULT_SNOOZE_MINUTES

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Reminder":
        """从 JSON 反序列化；字段缺失或类型不符时回落默认值。"""

        def _str(key: str, default: str = "") -> str:
            value = data.get(key)
            return value if isinstance(value, str) else default

        weekdays: list[int] = []
        week_value = data.get("weekdays")
        if isinstance(week_value, list):
            day_values: list[object] = cast("list[object]", week_value)
            weekdays = [v for v in day_values if isinstance(v, int)]
        obj = cls(
            id=_str("id"),
            title=_str("title"),
            content=_str("content"),
            rule=_str("rule", "once"),
            span=_as_bool(data.get("span"), False),
            date=_str("date"),
            time=_str("time", "09:00"),
            weekdays=weekdays,
            start_time=_as_time_text(data.get("start_time"),
                                     DEFAULT_WINDOW_START),
            end_time=_as_time_text(data.get("end_time"), DEFAULT_WINDOW_END),
            interval_minutes=_as_int(data.get("interval_minutes"),
                                     DEFAULT_INTERVAL_MINUTES),
            enabled=_as_bool(data.get("enabled", True)),
            snooze_minutes=_as_int(data.get("snooze_minutes"),
                                   DEFAULT_SNOOZE_MINUTES),
            created_at=_str("created_at"),
        )
        obj.weekdays = sorted(set(obj.weekdays))
        if obj.rule != "weekly":
            obj.weekdays = []
        return obj

    # ---------- 展示辅助 ----------
    def rule_text(self) -> str:
        if self.rule == "once":
            return f"单次 {self.date} {self.time}"
        span = (f"{self.start_time}-{self.end_time} "
                f"每{self.interval_minutes}分钟") if self.span else self.time
        if self.rule == "daily":
            return f"每天 {span}"
        if self.rule == "weekly":
            return f"每周{weekday_text(self.weekdays)} {span}"
        return f"{self.rule} {span}"

    def window_valid(self) -> bool:
        """时间段是否合法（end 需不早于 start；相等表示只提醒一次）。"""
        if self.rule == "once" or not self.span:
            return True
        try:
            sh, sm = parse_time(self.start_time)
            eh, em = parse_time(self.end_time)
        except ValueError:
            return False
        return (eh * 60 + em) >= (sh * 60 + sm)

    def state_text(self, now: datetime | None = None) -> str:
        """用于列表展示的状态文字。"""
        if not self.enabled:
            return "已暂停"
        if self.rule == "once":
            try:
                when = self.once_datetime()
                if when < (now or datetime.now()):
                    return "已过期"
            except ValueError:
                return "配置错误"
        if not self.window_valid():
            return "配置错误"
        return "启用"

    def once_datetime(self) -> datetime:
        if self.rule != "once":
            raise ValueError("only once reminders have once_datetime")
        hh, mm = parse_time(self.time)
        d = parse_date(self.date)
        return datetime(d.year, d.month, d.day, hh, mm)


_legacy_migrated = False


def app_dir() -> Path:
    """应用所在目录（数据、日志都写在这里，方便整体拷贝便携使用）：
    - 打包成 exe 时：exe 所在的文件夹
    - 源码运行时：项目根目录
    """
    try:
        if getattr(sys, "frozen", False):  # PyInstaller 打包环境
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent
    except Exception:
        return Path.cwd()


def default_data_path() -> Path:
    """数据文件保存在程序（exe）同一文件夹下的 reminders.json。"""
    global _legacy_migrated
    if not _legacy_migrated:
        _legacy_migrated = True
        _migrate_legacy_data()
    return app_dir() / "reminders.json"


def _migrate_legacy_data() -> None:
    """首次切换到 exe 同目录存储时，把旧版 %APPDATA%\\ReminderClock 里的
    reminders.json 拷过来，避免升级后任务“凭空消失”（不删除旧文件）。"""
    try:
        new = app_dir() / "reminders.json"
        if new.exists():
            return
        base = os.environ.get("APPDATA") or str(Path.home())
        old = Path(base) / "ReminderClock" / "reminders.json"
        if old.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            _ = shutil.copy2(old, new)
    except Exception:
        pass  # 迁移失败不阻塞启动


def _parse_json_object(text: str) -> dict[str, object] | None:
    """把文本解析为 dict；非法 JSON 或不是对象时返回 None。"""
    try:
        decoded = json.loads(text)  # pyright: ignore[reportAny]  # json 无类型标注，此边界处按 Any 处理
    except ValueError:
        return None
    if isinstance(decoded, dict):
        return cast("dict[str, object]", decoded)
    return None


def load_reminders(path: str | Path | None = None) -> list[Reminder]:
    p = Path(path) if path else default_data_path()
    if not p.exists():
        return []
    try:
        payload = _parse_json_object(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []  # 文件不存在或内容不是合法 JSON
    if payload is None:
        return []  # JSON 结构不是对象
    raw_items = payload.get("reminders", [])
    if not isinstance(raw_items, list):
        return []
    items: list[object] = cast("list[object]", raw_items)
    result: list[Reminder] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            item_map: dict[str, object] = cast("dict[str, object]", item)
            result.append(Reminder.from_dict(item_map))
        except Exception:
            continue  # 跳过损坏的条目，不阻塞整体加载
    return result


def save_reminders(reminders: list[Reminder], path: str | Path | None = None) -> None:
    p = Path(path) if path else default_data_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "version": 1,
        "reminders": [r.to_dict() for r in reminders],
    }
    _ = p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8")
