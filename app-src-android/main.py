#!/usr/bin/env python3
"""Minecraft 模组/插件汉化工具 - Android 普通版 (Kivy)

手机竖屏线性布局：
- 顶部固定标题
- 中间整体可上下滑动
- AI 引擎、翻译目标用一排按钮直接选择
- 最多四个翻译目录输入框
- 日志框、清空日志、进度条+预估时间、开始按钮依次排列
"""

import json
import os
import threading
import time
import traceback
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget

from core import (
    discover_target_dir,
    generate_plugin_patch,
    generate_resource_pack,
    process_jar_inplace,
    process_modpack,
    process_plugin_jar_inplace,
    process_server,
    scan_jars,
    summarize,
)
from translate import Translator

# ---------------------------------------------------------------------------
# 中文字体
# ---------------------------------------------------------------------------
def _setup_font():
    here = Path(__file__).resolve().parent
    bundled = [
        here / "fonts" / "simhei.ttf",
        here / "fonts" / "msyh.ttc",
        here / "fonts" / "NotoSansSC-VF.ttf",
    ]
    for path in bundled:
        try:
            if path.exists():
                LabelBase.register(name="ChineseFont", fn_regular=str(path))
                return "ChineseFont"
        except Exception:
            continue
    system = [
        "/system/fonts/NotoSansCJK-Regular.ttc",
        "/system/fonts/NotoSansCJKsc-Regular.otf",
        "/system/fonts/DroidSansFallback.ttf",
    ]
    for path in system:
        try:
            if Path(path).exists():
                LabelBase.register(name="ChineseFont", fn_regular=path)
                return "ChineseFont"
        except Exception:
            continue
    return None

FONT_NAME = _setup_font()

def _font_prop():
    return {"font_name": FONT_NAME} if FONT_NAME else {}

# ---------------------------------------------------------------------------
# 主题
# ---------------------------------------------------------------------------
THEME = {
    "bg": (0.96, 0.96, 0.96, 1),
    "fg": (0.15, 0.15, 0.15, 1),
    "accent": (0.26, 0.63, 0.28, 1),
    "accent_light": (0.85, 0.95, 0.86, 1),
    "warn": (0.95, 0.55, 0.15, 1),
    "hint": (0.45, 0.45, 0.45, 1),
    "white": (1, 1, 1, 1),
}

CONFIG_FILE = Path("/sdcard/Download/mc-chinese-config.json")
ERROR_LOG = Path("/sdcard/Download/mc-chinese-error.log")

def _write_error_log():
    try:
        ERROR_LOG.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass

def _request_android_permissions():
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.INTERNET,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.MANAGE_EXTERNAL_STORAGE,
        ])
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 通用控件
# ---------------------------------------------------------------------------
class CLabel(Label):
    """中文字体标签，自动换行。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("color", THEME["fg"])
        kwargs.setdefault("font_size", sp(15))
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        if FONT_NAME:
            kwargs.setdefault("font_name", FONT_NAME)
        self._fixed_height = "height" in kwargs
        super().__init__(**kwargs)
        self.bind(width=self._update_text_size)
        if not self._fixed_height:
            self.bind(texture_size=self._update_height)

    def _update_text_size(self, instance, width):
        self.text_size = (width, None)

    def _update_height(self, instance, size):
        if self.size_hint_y is None:
            self.height = max(size[1], dp(20))

class CButton(Button):
    def __init__(self, **kwargs):
        if FONT_NAME:
            kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", sp(15))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(48))
        super().__init__(**kwargs)

class CToggle(ToggleButton):
    def __init__(self, **kwargs):
        if FONT_NAME:
            kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", sp(14))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(44))
        kwargs.setdefault("group", kwargs.get("group", ""))
        super().__init__(**kwargs)

class CInput(TextInput):
    def __init__(self, **kwargs):
        if FONT_NAME:
            kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", sp(15))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(48))
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("padding", dp(10))
        kwargs.setdefault("background_color", (1, 1, 1, 1))
        kwargs.setdefault("foreground_color", THEME["fg"])
        kwargs.setdefault("cursor_color", THEME["accent"])
        super().__init__(**kwargs)

# ---------------------------------------------------------------------------
# 主界面
# ---------------------------------------------------------------------------
class MainLayout(BoxLayout):
    progress_value = NumericProperty(0)

    def __init__(self, **kwargs):
        try:
            super().__init__(orientation="vertical", **kwargs)
            Window.clearcolor = THEME["bg"]
            self._log_buffer = []
            self._start_time = None
            self._build_ui()
            self._load_config()
            self._request_permissions()
            Clock.schedule_interval(self._flush_logs, 0.3)
            Clock.schedule_interval(self._tick_eta, 1.0)
        except Exception:
            _write_error_log()
            raise

    def _request_permissions(self):
        Clock.schedule_once(lambda dt: _request_android_permissions(), 0.5)

    def _section_title(self, text):
        return CLabel(
            text=f"[b]{text}[/b]",
            markup=True,
            color=THEME["accent"],
            font_size=sp(17),
            size_hint_y=None,
            height=dp(28),
        )

    def _hint(self, text, height=dp(22)):
        return CLabel(
            text=text,
            color=THEME["hint"],
            font_size=sp(13),
            size_hint_y=None,
            height=height,
        )

    def _build_ui(self):
        # 顶部标题（固定）
        header = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(56),
            padding=(dp(12), dp(8)),
        )
        header.add_widget(CLabel(
            text="Minecraft 自动翻译工具",
            font_size=sp(20),
            bold=True,
            color=THEME["white"],
            halign="center",
            valign="middle",
            size_hint_y=1,
        ))
        header.background_color = THEME["accent"]
        self.add_widget(header)

        # 中间可滚动内容
        scroll = ScrollView(
            bar_width=dp(6),
            scroll_type=["content"],
        )
        content = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(10),
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))
        scroll.add_widget(content)
        self.add_widget(scroll)

        # 1. AI 选择
        content.add_widget(self._section_title("选择 AI 翻译引擎"))
        content.add_widget(self._hint("点击选择要使用的翻译引擎"))
        ai_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
        )
        self.ai_buttons = []
        ai_options = [
            ("多引擎自动", "multi_free"),
            ("百度翻译", "baidu_free"),
            ("有道翻译", "youdao_free"),
            ("LLM API", "llm"),
        ]
        for label, value in ai_options:
            btn = CToggle(text=label, group="ai", state="down" if value == "multi_free" else "normal")
            btn.value = value
            btn.bind(on_press=self._on_ai_change)
            self.ai_buttons.append(btn)
            ai_box.add_widget(btn)
        content.add_widget(ai_box)

        # 2. 翻译目标选择
        content.add_widget(self._section_title("选择翻译目标"))
        content.add_widget(self._hint("点击选择要翻译的内容类型"))
        target_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
        )
        self.target_buttons = []
        target_options = ["模组", "插件", "整合包", "服务器"]
        for label in target_options:
            btn = CToggle(text=label, group="target", state="down" if label == "模组" else "normal")
            btn.value = label
            btn.bind(on_press=self._on_target_change)
            self.target_buttons.append(btn)
            target_box.add_widget(btn)
        content.add_widget(target_box)

        # 3. 翻译输入区域（最多四个）
        content.add_widget(self._section_title("添加要翻译的目录"))
        content.add_widget(self._hint("最多可添加 4 个目录，留空的不处理"))
        self.input_items = []
        defaults = [
            "/sdcard/Download/mc-server",
            "",
            "",
            "",
        ]
        for i, default in enumerate(defaults, 1):
            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(54),
                spacing=dp(8),
            )
            inp = CInput(
                hint_text=f"第 {i} 个目录",
                text=default,
                size_hint_x=1,
            )
            btn = CButton(
                text="选择",
                size_hint_x=None,
                width=dp(70),
                background_color=THEME["accent"],
                color=THEME["white"],
            )
            btn.bind(on_release=lambda x, target=inp: self._open_chooser(target))
            row.add_widget(inp)
            row.add_widget(btn)
            content.add_widget(row)
            self.input_items.append(inp)

        # 4. 输出目录
        content.add_widget(self._section_title("输出目录"))
        out_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(54),
            spacing=dp(8),
        )
        self.output_path = CInput(
            hint_text="输出位置",
            text="/sdcard/Download/mc-chinese-output",
            size_hint_x=1,
        )
        out_btn = CButton(
            text="选择",
            size_hint_x=None,
            width=dp(70),
            background_color=THEME["accent"],
            color=THEME["white"],
        )
        out_btn.bind(on_release=lambda x: self._open_chooser(self.output_path))
        out_row.add_widget(self.output_path)
        out_row.add_widget(out_btn)
        content.add_widget(out_row)

        # 5. 翻译模式
        content.add_widget(self._section_title("翻译模式"))
        mode_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
        )
        self.mode_buttons = []
        for label in ["快速版", "完整版"]:
            btn = CToggle(text=label, group="mode", state="down" if label == "快速版" else "normal")
            btn.value = label
            self.mode_buttons.append(btn)
            mode_box.add_widget(btn)
        content.add_widget(mode_box)

        # 6. API 配置（仅 LLM 需要）
        content.add_widget(self._section_title("API 配置（选 LLM API 时填写）"))
        self.api_key = CInput(hint_text="API Key", password=True)
        content.add_widget(self.api_key)
        self.base_url = CInput(hint_text="Base URL（可选）")
        content.add_widget(self.base_url)
        self.model = CInput(hint_text="模型名称（默认 deepseek-chat）")
        content.add_widget(self.model)

        content.add_widget(self._section_title("请求延迟（秒）"))
        self.delay_input = CInput(text="0.05", hint_text="0.05")
        content.add_widget(self.delay_input)

        # 7. 日志框
        content.add_widget(self._section_title("运行日志"))
        self.log_box = TextInput(
            readonly=True,
            multiline=True,
            background_color=(1, 1, 1, 1),
            foreground_color=THEME["fg"],
            font_size=sp(13),
            size_hint_y=None,
            height=dp(180),
        )
        if FONT_NAME:
            self.log_box.font_name = FONT_NAME
        content.add_widget(self.log_box)

        # 8. 清空日志
        clear_btn = CButton(
            text="清空日志",
            background_color=(0.5, 0.5, 0.5, 1),
            color=THEME["white"],
        )
        clear_btn.bind(on_release=lambda x: setattr(self.log_box, "text", ""))
        content.add_widget(clear_btn)

        # 9. 进度条 + 预估时间
        content.add_widget(self._section_title("翻译进度"))
        self.progress_bar = ProgressBar(
            max=100,
            value=0,
            size_hint_y=None,
            height=dp(28),
        )
        content.add_widget(self.progress_bar)

        self.eta_label = CLabel(
            text="预计剩余时间：--",
            color=THEME["hint"],
            font_size=sp(13),
            size_hint_y=None,
            height=dp(24),
        )
        content.add_widget(self.eta_label)

        self.status_label = CLabel(
            text="状态：就绪",
            font_size=sp(15),
            size_hint_y=None,
            height=dp(26),
        )
        content.add_widget(self.status_label)

        # 底部留白
        content.add_widget(Widget(size_hint_y=None, height=dp(20)))

        # 底部开始按钮（固定）
        footer = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(68),
            padding=(dp(12), dp(8)),
        )
        self.start_btn = CButton(
            text="开始翻译",
            font_size=sp(17),
            height=dp(52),
            background_color=THEME["accent"],
            color=THEME["white"],
            bold=True,
        )
        self.start_btn.bind(on_release=self._start)
        footer.add_widget(self.start_btn)
        self.add_widget(footer)
