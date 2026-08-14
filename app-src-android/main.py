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
from kivy.graphics import Color, Rectangle
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
        ])
    except Exception:
        pass


def _check_all_files_permission():
    """检查 Android 11+ 的所有文件访问权限是否已开启。"""
    try:
        from jnius import autoclass

        Build = autoclass("android.os.Build")
        if Build.VERSION.SDK_INT < 30:
            return True

        Environment = autoclass("android.os.Environment")
        return bool(Environment.isExternalStorageManager())
    except Exception:
        return True


def _open_all_files_settings():
    """跳转到系统设置，让用户手动开启所有文件访问权限。"""
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
            self._has_all_files_permission = True
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
        def check(dt):
            ok = _check_all_files_permission()
            self._has_all_files_permission = ok
            if not ok:
                self._log("提示：Android 11+ 需要“所有文件访问权限”才能读取 FCL/mods 等目录")
                self._log("如果扫描不到 jar，请到系统设置中为本应用开启该权限")
        Clock.schedule_once(check, 1.0)

    def _update_header(self, instance, value):
        self._header_rect.pos = instance.pos
        self._header_rect.size = instance.size

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
        with header.canvas.before:
            Color(*THEME["accent"])
            self._header_rect = Rectangle(pos=header.pos, size=header.size)
        header.bind(pos=self._update_header, size=self._update_header)
        header.add_widget(CLabel(
            text="Minecraft 自动翻译工具",
            font_size=sp(20),
            bold=True,
            color=THEME["white"],
            halign="center",
            valign="middle",
            size_hint_y=1,
        ))
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

        # 4. 输出方式
        content.add_widget(self._section_title("输出方式"))
        content.add_widget(self._hint("选择一种处理方式，选中后下方会显示对应设置"))
        output_mode_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(96),
            spacing=dp(4),
        )
        self.output_mode_buttons = []
        for label, desc in [
            ("生成资源包/补丁", "生成可导入的资源包或补丁文件"),
            ("直接修改 jar", "直接修改原文件并备份为 .backup"),
        ]:
            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(44),
                spacing=dp(8),
            )
            btn = CToggle(
                text=label,
                group="output_mode",
                state="down" if label == "生成资源包/补丁" else "normal",
                size_hint_x=None,
                width=dp(36),
            )
            btn.value = label
            btn.bind(on_press=self._on_output_mode_change)
            self.output_mode_buttons.append(btn)
            row.add_widget(btn)
            row.add_widget(CLabel(
                text=f"{label}  {desc}",
                font_size=sp(14),
                color=THEME["fg"],
                valign="middle",
            ))
            output_mode_box.add_widget(row)
        content.add_widget(output_mode_box)

        # 5. 输出目录（根据输出方式显示/隐藏）
        self.output_section = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(4),
        )
        self.output_section_title = self._section_title("输出目录")
        self.output_section.add_widget(self.output_section_title)
        out_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(54),
            spacing=dp(8),
        )
        self.output_path = CInput(
            hint_text="资源包/补丁输出位置",
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
        self.output_section.add_widget(out_row)
        content.add_widget(self.output_section)

        # 直接修改模式说明
        self.inplace_hint = self._hint(
            "直接修改模式：原 jar 会自动备份为 .backup，无需填写输出目录",
            height=dp(40),
        )
        self.inplace_hint.opacity = 0
        self.inplace_hint.size_hint_y = None
        self.inplace_hint.height = 0
        content.add_widget(self.inplace_hint)

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

        # 根据默认输出方式刷新界面
        Clock.schedule_once(lambda dt: self._update_output_mode_ui(), 0)

    def _on_ai_change(self, btn):
        # 确保只有一个按下
        for b in self.ai_buttons:
            if b != btn:
                b.state = "normal"
        if self._get_ai_value() == "llm":
            self._log("提示：选择 LLM API 后请填写 API Key")

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
        if mode == "直接修改 jar":
            self.output_section.opacity = 0
            self.output_section.height = 0
            self.output_section.size_hint_y = None
            self.inplace_hint.opacity = 1
            self.inplace_hint.height = dp(40)
        else:
            self.output_section.opacity = 1
            self.output_section.height = dp(86)
            self.output_section.size_hint_y = None
            self.inplace_hint.opacity = 0
            self.inplace_hint.height = 0

    def _get_ai_value(self):
        for btn in self.ai_buttons:
            if btn.state == "down":
                return btn.value
        return "multi_free"

    def _get_target_value(self):
        for btn in self.target_buttons:
            if btn.state == "down":
                return btn.value
        return "模组"

    def _get_mode_value(self):
        for btn in self.mode_buttons:
            if btn.state == "down":
                return btn.value
        return "快速版"

    def _open_chooser(self, target_input):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        default_path = target_input.text.strip() or "/sdcard/Download"
        try:
            if not Path(default_path).exists():
                default_path = "/sdcard/Download"
        except Exception:
            default_path = "/sdcard/Download"

        popup = Popup(title="选择目录", content=content, size_hint=(0.94, 0.88))

        current_label = CLabel(
            text=f"当前：{default_path}",
            font_size=sp(14),
            size_hint_y=None,
            height=dp(32),
        )
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
                    up_btn = CButton(
                        text="[上级目录] ..",
                        size_hint_y=None,
                        height=dp(46),
                        background_color=(0.55, 0.55, 0.55, 1),
                        color=THEME["white"],
                    )
                    up_btn.bind(on_release=lambda x: load(parent))
                    list_box.add_widget(up_btn)

                for item in sorted(p.iterdir()):
                    if item.is_dir():
                        name = item.name
                        dir_btn = CButton(
                            text=f"[文件夹] {name}",
                            size_hint_y=None,
                            height=dp(46),
                            background_color=(0.75, 0.75, 0.75, 1),
                            color=THEME["fg"],
                        )
                        dir_btn.bind(on_release=lambda x, full=str(item): load(full))
                        list_box.add_widget(dir_btn)
            except Exception as exc:
                current_label.text = f"读取失败：{exc}"

        load(default_path)

        btn_box = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(10))
        cancel_btn = CButton(
            text="取消",
            background_color=(0.55, 0.55, 0.55, 1),
            color=THEME["white"],
        )
        cancel_btn.bind(on_release=popup.dismiss)
        select_btn = CButton(
            text="选择当前目录",
            background_color=THEME["accent"],
            color=THEME["white"],
        )
        select_btn.bind(on_release=select_current)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(select_btn)
        content.add_widget(btn_box)
        popup.open()

    def _log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        self._log_buffer.append(f"[{timestamp}] {msg}")

    @mainthread
    def _flush_logs(self, dt):
        if self._log_buffer:
            self.log_box.text += "\n".join(self._log_buffer) + "\n"
            self._log_buffer.clear()
            self.log_box.cursor = (0, len(self.log_box.text))

    def _set_progress(self, pct: float):
        Clock.schedule_once(lambda dt: setattr(self.progress_bar, "value", max(0.0, min(100.0, pct))), 0)

    def _tick_eta(self, dt):
        if self._start_time is None:
            return True
        elapsed = time.time() - self._start_time
        pct = self.progress_bar.value
        if pct > 1.0 and elapsed > 2.0:
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

    def _load_config(self):
        try:
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                inputs = cfg.get("inputs", ["/sdcard/Download/mc-server", "", "", ""])
                for i, inp in enumerate(self.input_items):
                    if i < len(inputs):
                        inp.text = inputs[i]
                self.output_path.text = cfg.get("output", "/sdcard/Download/mc-chinese-output")
                self._set_ai(cfg.get("engine", "多引擎自动"))
                self._set_target(cfg.get("target_type", "模组"))
                self._set_mode(cfg.get("mode", "快速版"))
                self._set_output_mode(cfg.get("output_mode", "生成资源包/补丁"))
                self.delay_input.text = cfg.get("delay", "0.05")
                self.api_key.text = cfg.get("api_key", "")
                self.base_url.text = cfg.get("base_url", "")
                self.model.text = cfg.get("model", "")
                Clock.schedule_once(lambda dt: self._update_output_mode_ui(), 0)
        except Exception:
            pass

    def _set_ai(self, text):
        for btn in self.ai_buttons:
            if btn.text == text:
                btn.state = "down"
            else:
                btn.state = "normal"

    def _set_target(self, text):
        for btn in self.target_buttons:
            if btn.text == text:
                btn.state = "down"
            else:
                btn.state = "normal"

    def _set_mode(self, text):
        for btn in self.mode_buttons:
            if btn.text == text:
                btn.state = "down"
            else:
                btn.state = "normal"

    def _set_output_mode(self, text):
        for btn in self.output_mode_buttons:
            if btn.text == text:
                btn.state = "down"
            else:
                btn.state = "normal"

    def _save_config(self):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            cfg = {
                "inputs": [inp.text for inp in self.input_items],
                "output": self.output_path.text,
                "engine": self._get_ai_button_text(),
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

    def _get_ai_button_text(self):
        for btn in self.ai_buttons:
            if btn.state == "down":
                return btn.text
        return "多引擎自动"

    def _target_map(self) -> str:
        mapping = {"模组": "mods", "插件": "plugins", "整合包": "modpack", "服务器": "server"}
        return mapping.get(self._get_target_value(), "mods")

    def _get_output_mode_value(self):
        for btn in self.output_mode_buttons:
            if btn.state == "down":
                return btn.value
        return "生成资源包/补丁"

    def _output_mode_map(self) -> str:
        mode = self._get_output_mode_value()
        mapping = {"生成资源包/补丁": "generate", "直接修改 jar": "inplace"}
        return mapping.get(mode, "generate")

    def _start(self, _):
        input_paths = [Path(inp.text.strip()) for inp in self.input_items if inp.text.strip()]
        input_paths = [p for p in input_paths if p.exists()]
        output_path = Path(self.output_path.text.strip())
        target = self._target_map()
        output_mode = self._output_mode_map()
        engine_name = self._get_ai_value()
        mode = "full" if self._get_mode_value() == "完整版" else "fast"
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
            self._log("正在跳转权限设置，请手动开启“允许管理所有文件”后返回重试")
            _open_all_files_settings()
            return

        self.start_btn.disabled = True
        self.start_btn.text = "翻译中..."
        self.status_label.text = "状态：正在翻译..."
        self.progress_bar.value = 0
        self.eta_label.text = "预计剩余时间：计算中..."
        self._start_time = time.time()
        self._save_config()
        self._log("=" * 30)
        self._log(f"开始翻译 | 目标：{self._get_target_value()} | 引擎：{self._get_ai_button_text()} | 模式：{self._get_mode_value()}")
        self._log(f"共 {len(input_paths)} 个目录待处理")

        thread = threading.Thread(
            target=self._worker,
            args=(input_paths, output_path, target, output_mode, engine_name, mode, api_key, base_url, model, delay),
            daemon=True,
        )
        thread.start()

    def _worker(self, input_paths, output_path, target, output_mode, engine_name, mode, api_key, base_url, model, delay):
        try:
            translator = Translator(
                engine=engine_name,
                api_key=api_key,
                base_url=base_url,
                model=model,
                mode=mode,
                delay=delay,
                cache_dir=Path("/sdcard/Download/.mc_mod_chinese/cache"),
            )
            self._log(translator.readiness_message())

            if not translator.is_ready():
                self._log("翻译引擎未就绪，请检查网络或 API Key")
                return

            output_path.mkdir(parents=True, exist_ok=True)
            total_paths = len(input_paths)

            for idx, input_path in enumerate(input_paths):
                base_pct = idx / total_paths * 100
                self._log(f"处理第 {idx + 1}/{total_paths} 个目录：{input_path}")

                def progress_cb(current: int, total: int, msg: str = ""):
                    inner_pct = (current / total * 100) if total > 0 else 0
                    self._set_progress(base_pct + inner_pct / total_paths)
                    if msg:
                        self._log(msg)

                if target == "modpack":
                    result = process_modpack(
                        minecraft_path=input_path,
                        translator=translator,
                        output_dir=output_path,
                        pack_format=15,
                        on_log=lambda m: self._log(m),
                        progress_cb=progress_cb,
                        mode=output_mode,
                    )
                    stats = summarize(result)
                    self._log(
                        f"整合包统计：共 {stats['total']} 个 jar，"
                        f"翻译 {stats['translated_mods']} 个，"
                        f"跳过 {stats['skipped_mods']} 个，"
                        f"失败 {stats['errors']} 个"
                    )
                elif target == "server":
                    result = process_server(
                        server_root=input_path,
                        translator=translator,
                        output_dir=output_path,
                        pack_format=15,
                        on_log=lambda m: self._log(m),
                        progress_cb=progress_cb,
                        mode=output_mode,
                    )
                    stats = summarize(result)
                    self._log(
                        f"服务器统计：共 {stats['total']} 个 jar，"
                        f"翻译 {stats['translated_mods']} 个，"
                        f"跳过 {stats['skipped_mods']} 个，"
                        f"失败 {stats['errors']} 个"
                    )
                elif target == "plugins":
                    plugins_dir = discover_target_dir(input_path, "plugins")
                    self._log(f"实际扫描目录：{plugins_dir}")
                    jars = scan_jars(plugins_dir, on_log=lambda m: self._log(m))
                    if not jars:
                        continue
                    if output_mode == "inplace":
                        presult = []
                        for jidx, jar in enumerate(jars):
                            presult.append(process_plugin_jar_inplace(jar, translator, backup=True, on_log=lambda m: self._log(m)))
                            progress_cb(jidx + 1, len(jars), f"直接修改插件 {jar.name}")
                    else:
                        presult = generate_plugin_patch(jars, translator, output_path, on_log=lambda m: self._log(m), progress_cb=progress_cb)
                    stats = summarize(presult)
                    if output_mode == "inplace":
                        self._log(f"插件已直接修改（原 jar 已备份为 .backup）")
                    self._log(
                        f"插件统计：共 {stats['total']} 个，"
                        f"翻译 {stats['translated_mods']} 个，"
                        f"跳过 {stats['skipped_mods']} 个，"
                        f"失败 {stats['errors']} 个"
                    )
                else:
                    mods_dir = discover_target_dir(input_path, "mods")
                    self._log(f"实际扫描目录：{mods_dir}")
                    jars = scan_jars(mods_dir, on_log=lambda m: self._log(m))
                    if not jars:
                        continue
                    if output_mode == "inplace":
                        mresult = []
                        for jidx, jar in enumerate(jars):
                            mresult.append(process_jar_inplace(jar, translator, backup=True, on_log=lambda m: self._log(m)))
                            progress_cb(jidx + 1, len(jars), f"直接修改模组 {jar.name}")
                    else:
                        mresult = generate_resource_pack(
                            jars,
                            translator,
                            output_path,
                            pack_name="AutoChineseResourcePack",
                            pack_format=15,
                            on_log=lambda m: self._log(m),
                            progress_cb=progress_cb,
                        )
                    stats = summarize(mresult)
                    if output_mode == "inplace":
                        self._log(f"模组已直接修改（原 jar 已备份为 .backup）")
                    self._log(
                        f"模组统计：共 {stats['total']} 个，"
                        f"翻译 {stats['translated_mods']} 个，"
                        f"跳过 {stats['skipped_mods']} 个，"
                        f"失败 {stats['errors']} 个"
                    )

            self._log("完成！")
        except Exception as exc:
            self._log(f"翻译失败：{exc}")
        finally:
            Clock.schedule_once(lambda dt: self._finish(), 0)

    @mainthread
    def _finish(self):
        self.start_btn.disabled = False
        self.start_btn.text = "开始翻译"
        self.status_label.text = "状态：就绪"
        self._set_progress(100.0)
        self.eta_label.text = "预计剩余时间：已完成"
        self._start_time = None


class MCChineseApp(App):
    def build(self):
        try:
            return MainLayout()
        except Exception:
            try:
                crash_path = Path("/sdcard/Download/mc-chinese-crash.log")
                crash_path.parent.mkdir(parents=True, exist_ok=True)
                crash_path.write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
            raise


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
