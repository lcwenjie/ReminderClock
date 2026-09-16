"""托盘图标与菜单（pystray + Pillow）。

注意：pystray 的回调运行在独立线程里，所有需要触碰 tkinter 的操作都必须
通过 app.post(...) 扔回主线程执行，本模块不直接操作任何 tk 控件。

类型说明：pystray 没有附带类型标注，因此这里用 Protocol 描述主程序
与托盘图标之间互相要用到的最小接口，方便静态检查通过。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # 仅用于类型检查；运行时 pystray 仍在函数内延迟导入
    from collections.abc import Callable

    import pystray


class AppHooks(Protocol):
    """主程序向托盘暴露的、可被跨线程安全调用的回调接口。"""

    def post(self, fn: Callable[[], None]) -> None: ...

    def show_main(self) -> None: ...

    def open_add(self) -> None: ...

    def request_quit(self) -> None: ...


class TrayIcon(Protocol):
    """本程序实际用到的托盘图标方法（pystray.Icon 的结构化描述）。"""

    def run_detached(self) -> None: ...

    def stop(self) -> None: ...


def _build_image():
    """画一个简单的蓝色圆角钟图标。

    Pillow 在这里才导入：让“缺依赖”能被 run() 捕获并给出友好提示，
    而不是在 import main 阶段就直接崩溃。
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 表盘底
    d.rounded_rectangle((2, 2, 61, 61), radius=16, fill=(37, 99, 235, 255))
    # 白色表盘
    d.ellipse((13, 13, 50, 50), fill=(255, 255, 255, 255))
    # 时针、分针
    d.line((31, 31, 31, 19), fill=(37, 99, 235, 255), width=4)
    d.line((31, 31, 41, 36), fill=(37, 99, 235, 255), width=3)
    # 轴心
    d.ellipse((28, 28, 34, 34), fill=(37, 99, 235, 255))
    return img


def create_tray(app: AppHooks) -> TrayIcon:
    """创建托盘图标；由调用方负责 run_detached()/stop()。"""
    import pystray

    def _open_main(_icon: object, _item: object) -> None:
        app.post(app.show_main)

    def _add_reminder(_icon: object, _item: object) -> None:
        app.post(app.open_add)

    def _quit(_icon: object, _item: object) -> None:
        app.post(app.request_quit)

    menu = pystray.Menu(
        pystray.MenuItem("打开提醒钟", _open_main, default=True),
        pystray.MenuItem("添加提醒", _add_reminder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _quit),
    )
    icon = pystray.Icon("reminder_clock", _build_image(), "提醒钟", menu)
    return icon
