#!/usr/bin/env python3
"""Minecraft 模组/插件汉化工具 - Android 版 (Kivy)

特性：
- 光影炫彩特效 UI（渐变标题栏、光晕动画、按钮点击动画）
- 免责声明弹窗（启动时显示）
- 底部导航：翻译 / 我的 / 支持
- 资源包版本选择、目标语言（简/繁）、多AI模块翻译、多目录输入
- 术语库管理、翻译历史记录、人工核对选项
- 真实进度与 ETA 预估
- 横屏 / 平板分栏适配
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
from kivy.graphics import Color, Ellipse, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import NumericProperty, StringProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget

from core import (
    discover_target_dir, generate_plugin_patch, generate_resource_pack,
    generate_review_document, process_jar_inplace, process_modpack,
    process_plugin_jar_inplace, process_server, scan_jars, summarize,
)
from translate import Translator


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------
def _setup_font():
    here = Path(__file__).resolve().parent
    for path in [here / "fonts" / "simhei.ttf", here / "fonts" / "msyh.ttc", here / "fonts" / "NotoSansSC-VF.ttf"]:
        try:
            if path.exists():
                LabelBase.register(name="ChineseFont", fn_regular=str(path))
                return "ChineseFont"
        except Exception:
            continue
    for path in ["/system/fonts/NotoSansCJK-Regular.ttc", "/system/fonts/NotoSansCJKsc-Regular.otf", "/system/fonts/DroidSansFallback.ttf"]:
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
# 主题（炫彩光影配色）
# ---------------------------------------------------------------------------
THEME = {
    "bg": (0.06, 0.07, 0.12, 1),
    "bg_card": (0.11, 0.13, 0.20, 1),
    "fg": (0.92, 0.93, 0.96, 1),
    "muted": (0.55, 0.58, 0.68, 1),
    "accent": (0.40, 0.75, 0.95, 1),
    "accent2": (0.65, 0.45, 0.95, 1),
    "gold": (0.98, 0.78, 0.30, 1),
    "success": (0.30, 0.80, 0.55, 1),
    "warn": (0.98, 0.60, 0.35, 1),
    "danger": (0.95, 0.40, 0.50, 1),
    "white": (1, 1, 1, 1),
}

CONFIG_FILE = Path("/sdcard/Download/mc-chinese-config.json")
ERROR_LOG = Path("/sdcard/Download/mc-chinese-error.log")
DATA_DIR = Path("/sdcard/Download/.mc_mod_chinese")
GLOSSARY_FILE = DATA_DIR / "glossary.json"
HISTORY_FILE = DATA_DIR / "history.json"

# 资源包版本 -> pack_format
PACK_FORMATS = [
    ("Minecraft 1.21.x", 34),
    ("Minecraft 1.20.x", 22),
    ("Minecraft 1.19.x", 13),
    ("Minecraft 1.18.x", 9),
    ("Minecraft 1.17.x", 7),
    ("Minecraft 1.16.x", 6),
    ("Minecraft 1.15.x", 5),
    ("Minecraft 1.14.x", 4),
    ("自定义版本", 15),
]


def _write_error_log():
    try:
        ERROR_LOG.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass


def _request_android_permissions():
    try:
        from android.permissions import request_permissions, Permission
        perms = [Permission.INTERNET, Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
        try:
            perms.append(Permission.MANAGE_EXTERNAL_STORAGE)
        except Exception:
            pass
        request_permissions(perms)
    except Exception:
        pass


def _check_all_files_permission():
    try:
        from jnius import autoclass
        Build = autoclass("android.os.Build")
        if Build.VERSION.SDK_INT < 30:
            return True
        Environment = autoclass("android.os.Environment")
        return bool(Environment.isExternalStorageManager())
    except Exception:
        return False


def _open_all_files_settings():
    try:
        from jnius import autoclass
        from android import activity
        Intent = autoclass("android.content.Intent")
        Settings = autoclass("android.provider.Settings")
        intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
        activity.startActivity(intent)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 通用控件
# ---------------------------------------------------------------------------
class CLabel(Label):
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
        kwargs.setdefault("background_color", (0.15, 0.17, 0.24, 1))
        kwargs.setdefault("foreground_color", THEME["fg"])
        kwargs.setdefault("cursor_color", THEME["accent"])
        super().__init__(**kwargs)


class GlowButton(Button):
    """带光晕动画的开始翻译按钮。"""
    def __init__(self, **kwargs):
        if FONT_NAME:
            kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", sp(18))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", THEME["white"])
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(56))
        super().__init__(**kwargs)
        self._pulse = 0
        self._anim_event = Clock.schedule_interval(self._animate, 0.05)

    def _animate(self, dt):
        self._pulse = (self._pulse + dt * 2) % 6.28
        self.canvas.before.clear()
        with self.canvas.before:
            alpha = 0.35 + 0.25 * (0.5 + 0.5 * (1 if False else 0))
            import math
            glow = 0.15 + 0.12 * (0.5 + 0.5 * math.sin(self._pulse))
            Color(0.40, 0.75, 0.95, glow)
            RoundedRectangle(pos=(self.x - dp(3), self.y - dp(3)),
                             size=(self.width + dp(6), self.height + dp(6)),
                             radius=[dp(14)])
            Color(0.65, 0.45, 0.95, glow * 0.8)
            RoundedRectangle(pos=(self.x - dp(1), self.y - dp(1)),
                             size=(self.width + dp(2), self.height + dp(2)),
                             radius=[dp(13)])
            Color(*THEME["accent"])
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])


class GradientHeader(BoxLayout):
    """渐变标题栏 + 光点装饰。"""
    def __init__(self, title="Minecraft 汉化工具", **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(64))
        kwargs.setdefault("padding", (dp(16), dp(10)))
        super().__init__(**kwargs)
        self._title = title
        self._t = 0
        self.bind(pos=self._redraw, size=self._redraw)
        self._event = Clock.schedule_interval(self._tick, 0.05)
        self.add_widget(CLabel(
            text=title, font_size=sp(22), bold=True,
            color=THEME["white"], halign="center", valign="middle", size_hint_y=1,
        ))

    def _tick(self, dt):
        self._t += dt
        self._redraw()

    def _redraw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            # 渐变背景（多段矩形模拟）
            steps = 20
            for i in range(steps):
                p = i / steps
                r = 0.20 + 0.35 * p
                g = 0.35 + 0.30 * p
                b = 0.70 + 0.20 * p
                Color(r, g, b, 1)
                h = self.height / steps
                Rectangle(pos=(self.x, self.y + h * i), size=(self.width, h + 1))
            # 光点
            import math
            for i in range(3):
                x = self.x + self.width * (0.2 + 0.3 * i)
                y = self.y + self.height * (0.5 + 0.3 * math.sin(self._t * 1.5 + i))
                Color(1, 1, 1, 0.10 + 0.05 * math.sin(self._t * 2 + i))
                Ellipse(pos=(x - dp(20), y - dp(20)), size=(dp(40), dp(40)))


# ---------------------------------------------------------------------------
# 翻译主屏幕
# ---------------------------------------------------------------------------
class TranslateScreen(Screen):
    progress_value = NumericProperty(0)
    eta_text = StringProperty("预计剩余时间：--")
    status_text = StringProperty("状态：就绪")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._log_buffer = []
        self._start_time = None
        self._has_all_files_permission = True
        self._processed_count = 0
        self._total_count = 0
        self._build_ui()
        self._load_config()
        self._request_permissions()
        Clock.schedule_interval(self._flush_logs, 0.3)
        Clock.schedule_interval(self._tick_eta, 1.0)

    # ---- 权限 ----
    def _request_permissions(self):
        Clock.schedule_once(lambda dt: _request_android_permissions(), 0.5)

        def check(dt):
            ok = _check_all_files_permission()
            self._has_all_files_permission = ok
            if not ok:
                self._log("提示：Android 11+ 需要「所有文件访问权限」才能读取 mods/plugins 等目录")
                self._log("如果扫描不到 jar，请到系统设置中为本应用开启该权限")

        Clock.schedule_once(check, 1.0)

    # ---- UI 构建 ----
    def _section_title(self, text):
        return CLabel(text=f"[b]{text}[/b]", markup=True, color=THEME["accent"],
                      font_size=sp(17), size_hint_y=None, height=dp(30))

    def _hint(self, text, height=dp(22)):
        return CLabel(text=text, color=THEME["muted"], font_size=sp(13),
                      size_hint_y=None, height=height)

    def _build_ui(self):
        root = BoxLayout(orientation="vertical")
        Window.clearcolor = THEME["bg"]
        root.add_widget(GradientHeader())

        scroll = ScrollView(bar_width=dp(6), scroll_type=["content"])
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        scroll.add_widget(content)
        root.add_widget(scroll)

        # 资源包版本
        content.add_widget(self._section_title("资源包版本"))
        self.version_spinner = Spinner(
            text=PACK_FORMATS[0][0],
            values=[v[0] for v in PACK_FORMATS],
            size_hint=(1, None), height=dp(48),
            background_color=(0.15, 0.17, 0.24, 1), color=THEME["fg"], font_size=sp(15),
        )
        if FONT_NAME:
            self.version_spinner.font_name = FONT_NAME
        content.add_widget(self.version_spinner)

        # 目标语言
        content.add_widget(self._section_title("目标语言"))
        lang_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        self.lang_buttons = []
        for label, val in [("简体中文", "zh-CN"), ("繁体中文", "zh-TW")]:
            btn = CToggle(text=label, group="lang", state="down" if val == "zh-CN" else "normal")
            btn.value = val
            self.lang_buttons.append(btn)
            lang_box.add_widget(btn)
        content.add_widget(lang_box)

        # AI 引擎选择
        content.add_widget(self._section_title("选择 AI 翻译引擎"))
        self.ai_options = [
            ("multi_ai", "多AI模块翻译"),
            ("baidu_free", "百度翻译"),
            ("youdao_free", "有道翻译"),
            ("tencent", "腾讯翻译"),
            ("caiyun", "彩云小译"),
            ("bing", "Bing 翻译"),
            ("papago", "Papago"),
            ("mymemory", "MyMemory"),
            ("libre", "LibreTranslate"),
            ("deepl_free", "DeepL"),
            ("google_free", "Google 免费"),
            ("linguee", "Linguee"),
            ("pons", "PONS"),
            ("yandex", "Yandex"),
            ("argos", "Argos（离线）"),
            ("llm", "LLM API"),
        ]
        self.ai_value_map = {d: v for v, d in self.ai_options}
        self.ai_display_map = {v: d for v, d in self.ai_options}
        self.ai_spinner = Spinner(
            text=self.ai_display_map["multi_ai"],
            values=[d for _, d in self.ai_options],
            size_hint=(1, None), height=dp(48),
            background_color=(0.15, 0.17, 0.24, 1), color=THEME["fg"], font_size=sp(15),
        )
        if FONT_NAME:
            self.ai_spinner.font_name = FONT_NAME
        content.add_widget(self.ai_spinner)

        # 翻译目标
        content.add_widget(self._section_title("选择翻译目标"))
        target_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        self.target_buttons = []
        for label in ["模组", "插件", "整合包", "服务器"]:
            btn = CToggle(text=label, group="target", state="down" if label == "模组" else "normal")
            btn.value = label
            btn.bind(on_press=self._on_target_change)
            self.target_buttons.append(btn)
            target_box.add_widget(btn)
        content.add_widget(target_box)

        # 多目录输入
        content.add_widget(self._section_title("添加要翻译的目录"))
        content.add_widget(self._hint("可添加多个目录，留空的不处理"))
        self.input_items = []
        defaults = ["/sdcard/Download/mc-server", "", "", ""]
        for i, default in enumerate(defaults, 1):
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54), spacing=dp(8))
            inp = CInput(hint_text=f"第 {i} 个目录", text=default, size_hint_x=1)
            btn = CButton(text="选择", size_hint_x=None, width=dp(70),
                          background_color=(0.20, 0.40, 0.60, 1), color=THEME["white"])
            btn.bind(on_release=lambda x, target=inp: self._open_chooser(target))
            row.add_widget(inp)
            row.add_widget(btn)
            content.add_widget(row)
            self.input_items.append(inp)

        # 输出方式
        content.add_widget(self._section_title("输出方式"))
        self.output_mode_buttons = []
        for label, desc in [("生成资源包", "生成可导入的资源包/补丁文件"),
                            ("直接修改", "直接修改原文件并备份为 .backup")]:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
            btn = CToggle(text=label, group="output_mode",
                          state="down" if label == "生成资源包" else "normal",
                          size_hint_x=None, width=dp(120))
            btn.value = label
            btn.bind(on_press=self._on_output_mode_change)
            self.output_mode_buttons.append(btn)
            row.add_widget(btn)
            row.add_widget(CLabel(text=desc, font_size=sp(13), color=THEME["muted"], valign="middle"))
            content.add_widget(row)

        # 输出目录
        self.output_section = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.output_section.add_widget(self._section_title("输出目录"))
        out_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(54), spacing=dp(8))
        self.output_path = CInput(hint_text="资源包/补丁输出位置",
                                  text="/sdcard/Download/mc-chinese-output", size_hint_x=1)
        out_btn = CButton(text="选择", size_hint_x=None, width=dp(70),
                          background_color=(0.20, 0.40, 0.60, 1), color=THEME["white"])
        out_btn.bind(on_release=lambda x: self._open_chooser(self.output_path))
        out_row.add_widget(self.output_path)
        out_row.add_widget(out_btn)
        self.output_section.add_widget(out_row)
        content.add_widget(self.output_section)

        self.inplace_hint = self._hint("直接修改模式：原 jar 会自动备份为 .backup，无需填写输出目录", height=dp(40))
        self.inplace_hint.opacity = 0
        self.inplace_hint.height = 0
        content.add_widget(self.inplace_hint)

        # 翻译模式
        content.add_widget(self._section_title("翻译模式"))
        mode_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        self.mode_buttons = []
        for label in ["快速版", "完整版"]:
            btn = CToggle(text=label, group="mode", state="down" if label == "快速版" else "normal")
            btn.value = label
            self.mode_buttons.append(btn)
            mode_box.add_widget(btn)
        content.add_widget(mode_box)

        # 人工核对
        review_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8))
        self.review_checkbox = CheckBox(active=False, size_hint_x=None, width=dp(40))
        review_row.add_widget(self.review_checkbox)
        review_row.add_widget(CLabel(text="是否需要人工核对（完成后生成核对文档）",
                                     font_size=sp(14), color=THEME["fg"], valign="middle"))
        content.add_widget(review_row)

        # 术语库 / 历史 入口
        entry_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        gloss_btn = CButton(text="术语库管理", background_color=(0.30, 0.50, 0.70, 1), color=THEME["white"])
        gloss_btn.bind(on_release=lambda x: self._open_glossary())
        entry_box.add_widget(gloss_btn)
        hist_btn = CButton(text="翻译历史", background_color=(0.45, 0.35, 0.65, 1), color=THEME["white"])
        hist_btn.bind(on_release=lambda x: self._open_history())
        entry_box.add_widget(hist_btn)
        content.add_widget(entry_box)

        # API 配置
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

        # 运行日志
        content.add_widget(self._section_title("运行日志"))
        self.log_box = TextInput(readonly=True, multiline=True,
                                 background_color=(0.10, 0.11, 0.16, 1),
                                 foreground_color=THEME["fg"], font_size=sp(13),
                                 size_hint_y=None, height=dp(180))
        if FONT_NAME:
            self.log_box.font_name = FONT_NAME
        content.add_widget(self.log_box)

        clear_btn = CButton(text="清空日志", background_color=(0.30, 0.32, 0.40, 1), color=THEME["white"])
        clear_btn.bind(on_release=lambda x: setattr(self.log_box, "text", ""))
        content.add_widget(clear_btn)

        # 进度
        content.add_widget(self._section_title("翻译进度"))
        self.progress_bar = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(28))
        content.add_widget(self.progress_bar)
        self.eta_label = CLabel(text="预计剩余时间：--", color=THEME["muted"],
                                font_size=sp(13), size_hint_y=None, height=dp(24))
        content.add_widget(self.eta_label)
        self.status_label = CLabel(text="状态：就绪", font_size=sp(15),
                                   color=THEME["success"], size_hint_y=None, height=dp(26))
        content.add_widget(self.status_label)

        content.add_widget(Widget(size_hint_y=None, height=dp(20)))

        # 开始按钮
        footer = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(72), padding=(dp(12), dp(8)))
        self.start_btn = GlowButton(text="开始翻译")
        self.start_btn.bind(on_release=self._start)
        footer.add_widget(self.start_btn)
        root.add_widget(footer)

        self.add_widget(root)
        Clock.schedule_once(lambda dt: self._update_output_mode_ui(), 0)

    # ---- 事件 ----
    def _on_target_change(self, btn):
        for b in self.target_buttons:
            if b != btn:
                b.state = "normal"

    def _on_output_mode_change(self, btn):
        for b in self.output_mode_buttons:
            if b != btn:
                b.state = "normal"
        self._update_output_mode_ui()

    def _update_output_mode_ui(self):
        mode = self._get_output_mode_value()
        if mode == "直接修改":
            self.output_section.opacity = 0
            self.output_section.height = 0
            self.inplace_hint.opacity = 1
            self.inplace_hint.height = dp(40)
        else:
            self.output_section.opacity = 1
            self.output_section.height = dp(86)
            self.inplace_hint.opacity = 0
            self.inplace_hint.height = 0

    def _update_history_card(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(*THEME["bg_card"])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(8)])

    def _get_ai_value(self):
        return self.ai_value_map.get(self.ai_spinner.text, "multi_ai")

    def _get_target_value(self):
        for btn in self.target_buttons:
            if btn.state == "down":
                return btn.value
        return "模组"

    def _get_lang_value(self):
        for btn in self.lang_buttons:
            if btn.state == "down":
                return btn.value
        return "zh-CN"

    def _get_mode_value(self):
        for btn in self.mode_buttons:
            if btn.state == "down":
                return btn.value
        return "快速版"

    def _get_output_mode_value(self):
        for btn in self.output_mode_buttons:
            if btn.state == "down":
                return btn.value
        return "生成资源包"

    def _get_pack_format(self):
        for name, fmt in PACK_FORMATS:
            if name == self.version_spinner.text:
                return fmt
        return 15

    # ---- 目录选择 ----
    def _open_chooser(self, target_input):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        default_path = target_input.text.strip() or "/sdcard/Download"
        try:
            if not Path(default_path).exists():
                default_path = "/sdcard/Download"
        except Exception:
            default_path = "/sdcard/Download"
        popup = Popup(title="选择目录", content=content, size_hint=(0.94, 0.88))
        current_label = CLabel(text=f"当前：{default_path}", font_size=sp(14), size_hint_y=None, height=dp(32))
        content.add_widget(current_label)
        scroll = ScrollView()
        list_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        list_box.bind(minimum_height=list_box.setter("height"))
        scroll.add_widget(list_box)
        content.add_widget(scroll)

        def select_current(_):
            target_input.text = current_label.text.replace("当前：", "")
            popup.dismiss()

        def load(path):
            current_label.text = f"当前：{path}"
            list_box.clear_widgets()
            try:
                p = Path(path)
                parent = str(p.parent)
                if parent != path and parent != ".":
                    up_btn = CButton(text="[上级目录] ..", size_hint_y=None, height=dp(46),
                                     background_color=(0.30, 0.32, 0.40, 1), color=THEME["white"])
                    up_btn.bind(on_release=lambda x: load(parent))
                    list_box.add_widget(up_btn)
                for item in sorted(p.iterdir()):
                    if item.is_dir():
                        dir_btn = CButton(text=f"[文件夹] {item.name}", size_hint_y=None, height=dp(46),
                                          background_color=(0.20, 0.22, 0.30, 1), color=THEME["fg"])
                        dir_btn.bind(on_release=lambda x, full=str(item): load(full))
                        list_box.add_widget(dir_btn)
            except Exception as exc:
                current_label.text = f"读取失败：{exc}"

        load(default_path)
        btn_box = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10))
        cancel_btn = CButton(text="取消", background_color=(0.30, 0.32, 0.40, 1), color=THEME["white"])
        cancel_btn.bind(on_release=popup.dismiss)
        select_btn = CButton(text="选择当前目录", background_color=(0.20, 0.60, 0.85, 1), color=THEME["white"])
        select_btn.bind(on_release=select_current)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(select_btn)
        content.add_widget(btn_box)
        popup.open()

    # ---- 术语库管理 ----
    def _load_glossary(self):
        try:
            if GLOSSARY_FILE.exists():
                return json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_glossary(self, glossary):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            GLOSSARY_FILE.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"保存术语库失败：{exc}")

    def _open_glossary(self):
        glossary = self._load_glossary()
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        content.add_widget(CLabel(text="术语库管理（英文 → 中文）", font_size=sp(16), bold=True,
                                  color=THEME["accent"], size_hint_y=None, height=dp(28)))
        content.add_widget(CLabel(text="命中术语将直接使用指定译文，跳过引擎调用", font_size=sp(12),
                                  color=THEME["muted"], size_hint_y=None, height=dp(20)))

        en_input = CInput(hint_text="英文原文，如 Diamond")
        zh_input = CInput(hint_text="中文译文，如 钻石")
        add_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        add_row.add_widget(en_input)
        add_row.add_widget(zh_input)
        content.add_widget(add_row)

        scroll = ScrollView()
        list_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        list_box.bind(minimum_height=list_box.setter("height"))
        scroll.add_widget(list_box)
        content.add_widget(scroll)

        def refresh():
            list_box.clear_widgets()
            if not glossary:
                list_box.add_widget(CLabel(text="（暂无术语，添加后翻译时将优先匹配）",
                                           font_size=sp(13), color=THEME["muted"], size_hint_y=None, height=dp(30)))
            for en, zh in glossary.items():
                row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
                row.add_widget(CLabel(text=f"{en}  →  {zh}", font_size=sp(13), color=THEME["fg"], valign="middle"))
                del_btn = CButton(text="删除", size_hint_x=None, width=dp(60),
                                  background_color=(0.55, 0.30, 0.40, 1), color=THEME["white"], font_size=sp(12))
                del_btn.bind(on_release=lambda x, k=en: (glossary.pop(k, None), refresh()))
                row.add_widget(del_btn)
                list_box.add_widget(row)

        def add_term(_):
            en = en_input.text.strip()
            zh = zh_input.text.strip()
            if en and zh:
                glossary[en] = zh
                self._save_glossary(glossary)
                en_input.text = ""
                zh_input.text = ""
                refresh()

        btn_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        add_btn = CButton(text="添加术语", background_color=(0.20, 0.60, 0.85, 1), color=THEME["white"])
        add_btn.bind(on_release=add_term)
        close_btn = CButton(text="关闭", background_color=(0.30, 0.32, 0.40, 1), color=THEME["white"])
        popup = Popup(title="术语库", content=content, size_hint=(0.94, 0.86))
        close_btn.bind(on_release=popup.dismiss)
        btn_row.add_widget(add_btn)
        btn_row.add_widget(close_btn)
        content.add_widget(btn_row)
        refresh()
        popup.open()

    # ---- 翻译历史 ----
    def _open_history(self):
        history = []
        try:
            if HISTORY_FILE.exists():
                history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        content.add_widget(CLabel(text="翻译历史记录", font_size=sp(16), bold=True,
                                  color=THEME["accent"], size_hint_y=None, height=dp(28)))
        scroll = ScrollView()
        list_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        list_box.bind(minimum_height=list_box.setter("height"))
        scroll.add_widget(list_box)
        content.add_widget(scroll)
        if not history:
            list_box.add_widget(CLabel(text="（暂无翻译记录）", font_size=sp(13),
                                       color=THEME["muted"], size_hint_y=None, height=dp(30)))
        for item in history:
            box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(72), padding=dp(8), spacing=dp(2))
            with box.canvas.before:
                Color(*THEME["bg_card"])
                RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(8)])
            box.bind(pos=self._update_history_card, size=self._update_history_card)
            box.add_widget(CLabel(text=f"{item.get('time','')}  |  {item.get('target','')}  |  {item.get('engine','')}  |  {item.get('mode','')}  |  {item.get('lang','')}",
                                  font_size=sp(12), color=THEME["accent"], valign="middle"))
            box.add_widget(CLabel(text=f"共 {item.get('total',0)} 个，翻译 {item.get('translated',0)} 个，失败 {item.get('failed',0)} 个",
                                  font_size=sp(12), color=THEME["muted"], valign="middle"))
            list_box.add_widget(box)
        close_btn = CButton(text="关闭", background_color=(0.30, 0.32, 0.40, 1), color=THEME["white"])
        close_btn.bind(on_release=lambda x: None)
        popup = Popup(title="历史记录", content=content, size_hint=(0.94, 0.86))
        close_btn.bind(on_release=popup.dismiss)
        content.add_widget(close_btn)
        popup.open()

    # ---- 日志 ----
    def _log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self._log_buffer.append(f"[{timestamp}] {msg}")

    @mainthread
    def _flush_logs(self, dt):
        if self._log_buffer:
            self.log_box.text += "\n".join(self._log_buffer) + "\n"
            self._log_buffer.clear()
            self.log_box.cursor = (0, len(self.log_box.text))

    # ---- 进度与 ETA ----
    def _set_progress(self, pct: float):
        Clock.schedule_once(lambda dt: setattr(self.progress_bar, "value", max(0.0, min(100.0, pct))), 0)

    def _tick_eta(self, dt):
        if self._start_time is None:
            return True
        elapsed = time.time() - self._start_time
        pct = self.progress_bar.value
        if pct > 1.0 and elapsed > 1.0:
            total_est = elapsed / (pct / 100.0)
            remaining = max(0, total_est - elapsed)
            if remaining < 60:
                eta = f"预计剩余时间：{remaining:.0f} 秒"
            elif remaining < 3600:
                eta = f"预计剩余时间：{remaining / 60:.1f} 分钟"
            else:
                eta = f"预计剩余时间：{remaining / 3600:.1f} 小时"
        else:
            eta = "预计剩余时间：计算中..."
        self.eta_label.text = eta
        return True

    # ---- 配置 ----
    def _load_config(self):
        try:
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                inputs = cfg.get("inputs", ["/sdcard/Download/mc-server", "", "", ""])
                for i, inp in enumerate(self.input_items):
                    if i < len(inputs):
                        inp.text = inputs[i]
                self.output_path.text = cfg.get("output", "/sdcard/Download/mc-chinese-output")
                self._set_ai(cfg.get("engine", "多AI模块翻译"))
                self._set_target(cfg.get("target_type", "模组"))
                self._set_mode(cfg.get("mode", "快速版"))
                self._set_output_mode(cfg.get("output_mode", "生成资源包"))
                self.delay_input.text = cfg.get("delay", "0.05")
                self.api_key.text = cfg.get("api_key", "")
                self.base_url.text = cfg.get("base_url", "")
                self.model.text = cfg.get("model", "")
                Clock.schedule_once(lambda dt: self._update_output_mode_ui(), 0)
        except Exception:
            pass

    def _set_ai(self, text):
        if text in self.ai_value_map:
            self.ai_spinner.text = text
        elif text in self.ai_display_map:
            self.ai_spinner.text = self.ai_display_map[text]
        else:
            self.ai_spinner.text = self.ai_display_map.get("multi_ai", "多AI模块翻译")

    def _set_target(self, text):
        for btn in self.target_buttons:
            btn.state = "down" if btn.text == text else "normal"

    def _set_mode(self, text):
        for btn in self.mode_buttons:
            btn.state = "down" if btn.text == text else "normal"

    def _set_output_mode(self, text):
        for btn in self.output_mode_buttons:
            btn.state = "down" if btn.text == text else "normal"

    def _save_config(self):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            cfg = {
                "inputs": [inp.text for inp in self.input_items],
                "output": self.output_path.text,
                "engine": self.ai_spinner.text,
                "target_type": self._get_target_value(),
                "mode": self._get_mode_value(),
                "output_mode": self._get_output_mode_value(),
                "delay": self.delay_input.text,
                "api_key": self.api_key.text,
                "base_url": self.base_url.text,
                "model": self.model.text,
            }
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"保存配置失败：{exc}")

    def _target_map(self) -> str:
        return {"模组": "mods", "插件": "plugins", "整合包": "modpack", "服务器": "server"}.get(self._get_target_value(), "mods")

    def _output_mode_map(self) -> str:
        return "inplace" if self._get_output_mode_value() == "直接修改" else "generate"

    # ---- 开始翻译 ----
    def _start(self, _):
        raw_paths = [Path(inp.text.strip()) for inp in self.input_items if inp.text.strip()]
        input_paths = []
        for p in raw_paths:
            if p.exists():
                input_paths.append(p)
            else:
                self._log(f"路径不存在或无权访问，已忽略：{p}")
        output_path = Path(self.output_path.text.strip())
        target = self._target_map()
        output_mode = self._output_mode_map()
        engine_name = self._get_ai_value()
        mode = "full" if self._get_mode_value() == "完整版" else "fast"
        target_lang = self._get_lang_value()
        api_key = self.api_key.text.strip() or None
        base_url = self.base_url.text.strip() or None
        model = self.model.text.strip() or "deepseek-chat"
        try:
            delay = float(self.delay_input.text.strip() or "0.05")
        except ValueError:
            delay = 0.05

        if not input_paths:
            self._log("错误：至少填写一个有效的输入目录")
            return
        if engine_name == "llm" and not api_key:
            self._log("错误：选择 LLM API 时必须填写 API Key")
            return
        if not getattr(self, "_has_all_files_permission", True):
            self._log("警告：未开启所有文件访问权限，可能导致无法读取目录")
            self._log("正在跳转权限设置，请手动开启「允许管理所有文件」后返回重试")
            _open_all_files_settings()
            return

        self.start_btn.disabled = True
        self.start_btn.text = "翻译中..."
        self.status_label.color = THEME["warn"]
        self.status_label.text = "状态：正在翻译..."
        self.progress_bar.value = 0
        self.eta_label.text = "预计剩余时间：计算中..."
        self._start_time = time.time()
        self._save_config()
        self._log("=" * 30)
        self._log(f"开始翻译 | 目标：{self._get_target_value()} | 引擎：{self.ai_spinner.text} | 模式：{self._get_mode_value()} | 语言：{('繁体' if target_lang.endswith('TW') else '简体')}中文")
        self._log(f"共 {len(input_paths)} 个目录待处理")

        thread = threading.Thread(
            target=self._worker,
            args=(input_paths, output_path, target, output_mode, engine_name, mode, target_lang, api_key, base_url, model, delay),
            daemon=True,
        )
        thread.start()

    def _worker(self, input_paths, output_path, target, output_mode, engine_name, mode, target_lang, api_key, base_url, model, delay):
        # 加载术语库
        glossary = {}
        try:
            if GLOSSARY_FILE.exists():
                glossary = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

        try:
            translator = Translator(
                engine=engine_name, api_key=api_key, base_url=base_url, model=model,
                mode=mode, target=target_lang, delay=delay, glossary=glossary,
                cache_dir=DATA_DIR / "cache", on_log=lambda m: self._log(m),
            )
            self._log(translator.readiness_message())
            if not translator.is_ready():
                self._log("翻译引擎未就绪，请检查网络或 API Key")
                return

            output_path.mkdir(parents=True, exist_ok=True)
            total_paths = len(input_paths)
            all_results = []

            for idx, input_path in enumerate(input_paths):
                base_pct = idx / total_paths * 100
                self._log(f"处理第 {idx + 1}/{total_paths} 个目录：{input_path}")

                def progress_cb(current: int, total: int, msg: str = ""):
                    inner_pct = (current / total * 100) if total > 0 else 0
                    self._set_progress(base_pct + inner_pct / total_paths)
                    if msg:
                        self._log(msg)

                if target == "modpack":
                    result = process_modpack(input_path, translator, output_path, pack_format=self._get_pack_format(),
                                              on_log=lambda m: self._log(m), progress_cb=progress_cb, mode=output_mode)
                elif target == "server":
                    result = process_server(input_path, translator, output_path, pack_format=self._get_pack_format(),
                                             on_log=lambda m: self._log(m), progress_cb=progress_cb, mode=output_mode)
                elif target == "plugins":
                    plugins_dir = discover_target_dir(input_path, "plugins")
                    self._log(f"实际扫描目录：{plugins_dir}")
                    jars = scan_jars(plugins_dir, on_log=lambda m: self._log(m))
                    if not jars:
                        self._log(f"未在 {plugins_dir} 找到任何 jar 文件，跳过该目录")
                        continue
                    if output_mode == "inplace":
                        result = [process_plugin_jar_inplace(j, translator, backup=True, on_log=lambda m: self._log(m)) for j in jars]
                        for jidx, j in enumerate(jars):
                            progress_cb(jidx + 1, len(jars), f"直接修改插件 {j.name}")
                    else:
                        result = generate_plugin_patch(jars, translator, output_path, on_log=lambda m: self._log(m), progress_cb=progress_cb)
                else:
                    mods_dir = discover_target_dir(input_path, "mods")
                    self._log(f"实际扫描目录：{mods_dir}")
                    jars = scan_jars(mods_dir, on_log=lambda m: self._log(m))
                    if not jars:
                        self._log(f"未在 {mods_dir} 找到任何 jar 文件，跳过该目录")
                        continue
                    if output_mode == "inplace":
                        result = [process_jar_inplace(j, translator, backup=True, on_log=lambda m: self._log(m)) for j in jars]
                        for jidx, j in enumerate(jars):
                            progress_cb(jidx + 1, len(jars), f"直接修改模组 {j.name}")
                    else:
                        result = generate_resource_pack(jars, translator, output_path, pack_name="AutoChineseResourcePack",
                                                        pack_format=self._get_pack_format(), on_log=lambda m: self._log(m), progress_cb=progress_cb)

                all_results.extend(result)
                stats = summarize(result)
                self._log(f"统计：共 {stats['total']} 个，翻译 {stats['translated_mods']} 个，跳过 {stats['skipped_mods']} 个，失败 {stats['errors']} 个")

            # 人工核对文档
            if self.review_checkbox.active and all_results:
                generate_review_document(all_results, output_path, translator, on_log=lambda m: self._log(m))

            # 保存历史记录
            self._save_history(all_results, input_paths, output_path, engine_name, mode, target_lang)

            self._log("完成！")
        except Exception as exc:
            self._log(f"翻译失败：{exc}")
        finally:
            Clock.schedule_once(lambda dt: self._finish(), 0)

    def _save_history(self, results, input_paths, output_path, engine_name, mode, target_lang):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            history = []
            if HISTORY_FILE.exists():
                history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            stats = summarize(results)
            history.insert(0, {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "target": self._get_target_value(),
                "engine": self.ai_spinner.text,
                "mode": "完整版" if mode == "full" else "快速版",
                "lang": "繁体中文" if target_lang.endswith("TW") else "简体中文",
                "dirs": len(input_paths),
                "total": stats["total"],
                "translated": stats["translated_mods"],
                "failed": stats["errors"],
                "output": str(output_path),
            })
            history = history[:50]
            HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"保存历史记录失败：{exc}")

    @mainthread
    def _finish(self):
        self.start_btn.disabled = False
        self.start_btn.text = "开始翻译"
        self.status_label.color = THEME["success"]
        self.status_label.text = "状态：就绪"
        self._set_progress(100.0)
        self.eta_label.text = "预计剩余时间：已完成"
        self._start_time = None


# ---------------------------------------------------------------------------
# 我的（账号）页面
# ---------------------------------------------------------------------------
class ProfileScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical")
        root.add_widget(GradientHeader(title="我的"))
        scroll = ScrollView(bar_width=dp(6))
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        scroll.add_widget(content)
        root.add_widget(scroll)

        # 头像 + 昵称
        avatar_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(80), spacing=dp(14))
        avatar = BoxLayout(size_hint_x=None, width=dp(64))
        with avatar.canvas.before:
            Color(*THEME["accent"])
            Ellipse(pos=(0, 0), size=(dp(64), dp(64)))
        avatar.add_widget(CLabel(text="🎮", font_size=sp(32), halign="center", valign="middle", color=THEME["white"]))
        avatar_box.add_widget(avatar)
        info_box = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(64))
        info_box.add_widget(CLabel(text="本地用户", font_size=sp(18), bold=True, color=THEME["fg"]))
        info_box.add_widget(CLabel(text="数据均存储于本设备，无需登录", font_size=sp(13), color=THEME["muted"]))
        avatar_box.add_widget(info_box)
        content.add_widget(avatar_box)

        content.add_widget(self._card("使用说明",
            "本工具用于将 Minecraft 模组/插件/整合包/服务器中的英文语言文件翻译为中文。\n"
            "翻译由第三方免费引擎或您自填的 LLM API 提供，结果仅供参考。"))

        content.add_widget(self._card("免责声明",
            "本应用仅为翻译辅助工具，使用过程中如出现翻译错误、文件损坏、数据丢失、"
            "设备异常、网络问题、权限冲突、兼容性问题等任何情况，均与本应用开发者无关，"
            "用户需自行承担使用风险。建议操作前备份原文件。"))

        content.add_widget(self._card("数据存储位置",
            f"配置：{CONFIG_FILE}\n缓存：{DATA_DIR / 'cache'}\n术语库：{GLOSSARY_FILE}\n历史：{HISTORY_FILE}"))

        content.add_widget(self._card("关于",
            "Minecraft 汉化工具 · Android 版\n基于 Kivy + Python + buildozer 打包\n版本 2.0.0"))

        content.add_widget(Widget(size_hint_y=None, height=dp(20)))
        self.add_widget(root)

    def _card(self, title, body):
        box = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(14), spacing=dp(6))
        with box.canvas.before:
            Color(*THEME["bg_card"])
            RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(12)])
        box.bind(pos=self._update_card, size=self._update_card)
        box.add_widget(CLabel(text=title, font_size=sp(16), bold=True, color=THEME["accent"], size_hint_y=None, height=dp(24)))
        body_label = CLabel(text=body, font_size=sp(13), color=THEME["muted"])
        body_label.bind(texture_size=lambda inst, size: setattr(inst, "height", max(size[1], dp(20))))
        body_label.size_hint_y = None
        box.add_widget(body_label)
        box.height = dp(24) + dp(60)
        return box

    def _update_card(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(*THEME["bg_card"])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(12)])


# ---------------------------------------------------------------------------
# 支持（VIP）页面
# ---------------------------------------------------------------------------
class SupportScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical")
        root.add_widget(GradientHeader(title="支持开发者"))
        scroll = ScrollView(bar_width=dp(6))
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        scroll.add_widget(content)
        root.add_widget(scroll)

        content.add_widget(CLabel(text="感谢您使用本工具！", font_size=sp(18), bold=True, color=THEME["fg"], size_hint_y=None, height=dp(28)))
        content.add_widget(CLabel(text="以下为赞助档位，支持开发者持续维护与优化。", font_size=sp(13), color=THEME["muted"], size_hint_y=None, height=dp(24)))

        # 屏风档位
        content.add_widget(self._tier_card("屏风", "¥3", THEME["accent"], [
            "提前获得新版本测试资格",
            "解锁专属小彩蛋",
        ]))

        # 波澜档位
        content.add_widget(self._tier_card("波澜", "¥10", THEME["accent2"], [
            "包含「屏风」全部权益",
            "可向开发者建议新增内容",
            "解锁更多界面配色主题",
            "优先反馈与问题响应",
        ]))

        content.add_widget(self._card("说明",
            "本工具完全免费使用，赞助为自愿行为。\n"
            "若您希望支持开发者，可通过上方档位进行赞助，\n"
            "解锁的彩蛋与配色将在后续版本中陆续上线。"))

        content.add_widget(Widget(size_hint_y=None, height=dp(20)))
        self.add_widget(root)

    def _tier_card(self, name, price, color, benefits):
        box = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(16), spacing=dp(8))
        with box.canvas.before:
            Color(*THEME["bg_card"])
            RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(14)])
        box.bind(pos=self._update_card, size=self._update_card)

        head = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40))
        head.add_widget(CLabel(text=name, font_size=sp(20), bold=True, color=color, size_hint_x=1))
        head.add_widget(CLabel(text=price, font_size=sp(20), bold=True, color=THEME["gold"], halign="right", size_hint_x=None, width=dp(80)))
        box.add_widget(head)

        for b in benefits:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
            row.add_widget(CLabel(text="✦", font_size=sp(14), color=color, size_hint_x=None, width=dp(20)))
            row.add_widget(CLabel(text=b, font_size=sp(13), color=THEME["fg"], valign="middle"))
            box.add_widget(row)

        btn = CButton(text=f"支持「{name}」", background_color=color, color=THEME["white"], size_hint_y=None, height=dp(44))
        box.add_widget(btn)
        box.height = dp(40) + dp(24) * len(benefits) + dp(44) + dp(32)
        return box

    def _card(self, title, body):
        box = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(14), spacing=dp(6))
        with box.canvas.before:
            Color(*THEME["bg_card"])
            RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(12)])
        box.bind(pos=self._update_card, size=self._update_card)
        box.add_widget(CLabel(text=title, font_size=sp(16), bold=True, color=THEME["accent"], size_hint_y=None, height=dp(24)))
        body_label = CLabel(text=body, font_size=sp(13), color=THEME["muted"])
        body_label.bind(texture_size=lambda inst, size: setattr(inst, "height", max(size[1], dp(20))))
        body_label.size_hint_y = None
        box.add_widget(body_label)
        box.height = dp(24) + dp(60)
        return box

    def _update_card(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(*THEME["bg_card"])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(12)])


# ---------------------------------------------------------------------------
# 免责声明弹窗
# ---------------------------------------------------------------------------
def show_disclaimer(on_agree):
    content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
    content.add_widget(CLabel(text="免责声明", font_size=sp(20), bold=True, color=THEME["gold"],
                              halign="center", size_hint_y=None, height=dp(32)))
    body = CLabel(
        text=("本应用仅为 Minecraft 游戏内容翻译工具，翻译结果由第三方翻译引擎或您自填的 LLM API 提供。\n\n"
              "使用本应用过程中，如出现翻译错误、文件损坏、数据丢失、设备异常、网络问题、"
              "权限冲突、兼容性问题等任何情况，均与本应用开发者无关，用户需自行承担使用风险。\n\n"
              "建议在操作前备份原文件。使用本应用即表示您已阅读并同意本免责声明。"),
        font_size=sp(14), color=THEME["fg"], halign="left", valign="top",
    )
    body.bind(texture_size=lambda inst, size: setattr(inst, "height", max(size[1], dp(120))))
    body.size_hint_y = None
    content.add_widget(body)
    agree_btn = CButton(text="我已知晓并同意", background_color=(0.20, 0.60, 0.85, 1), color=THEME["white"])
    content.add_widget(agree_btn)
    popup = Popup(title="", content=content, size_hint=(0.92, 0.82), auto_dismiss=False,
                  separator_color=(0, 0, 0, 0))
    agree_btn.bind(on_release=lambda x: (popup.dismiss(), on_agree()))
    popup.open()


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------
class TabBar(BoxLayout):
    """底部导航栏：翻译 / 我的 / 支持。"""
    def __init__(self, app_ref, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(60))
        kwargs.setdefault("spacing", dp(2))
        super().__init__(**kwargs)
        self.app_ref = app_ref
        self.tabs = []
        for label, name, icon in [("翻译", "translate", "🌐"), ("我的", "profile", "👤"), ("支持", "support", "💖")]:
            btn = CButton(text=f"{icon}\n{label}", font_size=sp(12),
                          background_color=(0.10, 0.11, 0.16, 1), color=THEME["muted"])
            btn.bind(on_release=lambda x, n=name: self.switch(n))
            self.tabs.append((btn, name))
            self.add_widget(btn)
        self.highlight("translate")

    def switch(self, name):
        self.app_ref.sm.current = name
        self.highlight(name)

    def highlight(self, name):
        for btn, n in self.tabs:
            if n == name:
                btn.background_color = (0.20, 0.40, 0.60, 1)
                btn.color = THEME["accent"]
            else:
                btn.background_color = (0.10, 0.11, 0.16, 1)
                btn.color = THEME["muted"]


class MCChineseApp(App):
    def build(self):
        try:
            root = BoxLayout(orientation="vertical")
            self.sm = ScreenManager()
            self.translate_screen = TranslateScreen(name="translate")
            self.sm.add_widget(self.translate_screen)
            self.sm.add_widget(ProfileScreen(name="profile"))
            self.sm.add_widget(SupportScreen(name="support"))
            root.add_widget(self.sm)
            root.add_widget(TabBar(self))
            return root
        except Exception:
            _write_error_log()
            raise

    def on_start(self):
        def agree():
            pass
        Clock.schedule_once(lambda dt: show_disclaimer(agree), 0.3)


if __name__ == "__main__":
    try:
        MCChineseApp().run()
    except Exception:
        try:
            crash_path = Path("/sdcard/Download/mc-chinese-crash.log")
            crash_path.parent.mkdir(parents=True, exist_ok=True)
            crash_path.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise