"""应用版本号：以时间命名，格式 YYYYMMDD-HHMM，例如 20260910-1136。

打包时由 build.bat 调用 write_stamp() 自动改写成打包时刻的时间戳，
因此每个发布包都带唯一、可按时间排序的版本号；直接运行源码时用文件里
记录的值。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

#: 当前版本号（YYYYMMDD-HHMM）。build.bat 打包前会自动改写这一行。
APP_VERSION = "20260914-1712"


def timestamp(moment: datetime | None = None) -> str:
    """返回给定时刻（默认现在）对应的版本号字符串。"""
    d = moment or datetime.now()
    return f"{d.year:04d}{d.month:02d}{d.day:02d}-{d.hour:02d}{d.minute:02d}"


def write_stamp(moment: datetime | None = None) -> str:
    """把本文件里的 APP_VERSION 改写为给定时刻的时间戳，并返回新版本号。

    供 build.bat 在打包前调用，保证发布包版本号 = 打包时间。
    """
    value = timestamp(moment)
    path = Path(__file__)
    text = path.read_text(encoding="utf-8")
    new_text = re.sub(r'^APP_VERSION = ".*"$', f'APP_VERSION = "{value}"',
                      text, count=1, flags=re.M)
    if new_text != text:
        _ = path.write_text(new_text, encoding="utf-8")
    return value
