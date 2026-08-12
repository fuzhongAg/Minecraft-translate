#!/usr/bin/env python3
"""Minecraft 模组/插件汉化工具 - Android 普通版 (Kivy)

简洁稳定主题，功能与完整版一致：进度条、预计时间、可滚动日志、
引擎选择、目标类型选择、API 配置、权限请求等。
"""

import json
import os
import threading
import time
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from core import (
    discover_target_dir,
    generate_plugin_patch,
    generate_resource_pack,
    process_modpack,
    process_server,
    scan_jars,
    summarize,
)
from translate import Translator


# ---------------------------------------------------------------------------
# 主题色（简洁白灰 + 绿色强调）
# ---------------------------------------------------------------------------
THEME = {
    "bg": (0.96, 0.96, 0.96, 1),             # 浅灰背景
    "card": (1, 1, 1, 1),                    # 白色卡片
    "card_border": (0.78, 0.78, 0.78, 1),    # 灰边框
    "fg": (0.15, 0.15, 0.15, 1),             # 深灰文字
    "accent": (0.25, 0.62, 0.20, 1),         # 按钮绿
    "accent_dark": (0.16, 0.45, 0.14, 1),    # 按下绿
    "gold": (0.25, 0.62, 0.20, 1),           # 进度条绿
    "warn": (0.95, 0.55, 0.15, 1),           # 橙色
    "error": (0.85, 0.20, 0.20, 1),          # 红色
    "hint": (0.40, 0.40, 0.40, 1),           # 灰色提示
}

CONFIG_FILE = Path("/sdcard/Download/mc-chinese-config.json")


def _request_android_permissions():
    """运行时请求安卓存储权限。"""
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([
            Permission.INTERNET,
            Permission.READ_EXTERNAL_STORAGE,
            Permission.WRITE_EXTERNAL_STORAGE,
        ])
    except Exception:
        pass


class FeatureHeader(BoxLayout):
    """顶部标题栏。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, height=70, **kwargs)
        with self.canvas.before:
            Color(*THEME["accent"])
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update, size=self._update)

        title = Label(
            text="[b]MC 自动中文化[/b]  普通版",
            markup=True,
            font_size=20,
            color=(1, 1, 1, 1),
            halign="center",
        )
        self.add_widget(title)

    def _update(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class FeatureCard(BoxLayout):
    """带边框和背景的卡片容器。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=10, spacing=6, **kwargs)
        with self.canvas.before:
            Color(*THEME["card"])
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[6])
            Color(*THEME["card_border"])
            self._line = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, 6), width=1)
        self.bind(pos=self._update, size=self._update)

    def _update(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._line.rounded_rectangle = (self.x, self.y, self.width, self.height, 6)


class FeatureButton(Button):
    """普通版按钮。"""

    def __init__(self, variant="primary", **kwargs):
        bg = THEME["accent"] if variant == "primary" else THEME["warn"] if variant == "warn" else (0.55, 0.55, 0.55, 1)
        super().__init__(
            background_color=bg,
            background_normal="",
            color=(1, 1, 1, 1),
            bold=True,
            font_size=15,
            **kwargs,
        )


class FeatureSpinner(Spinner):
    """普通版下拉框。"""

    def __init__(self, **kwargs):
        super().__init__(
            background_color=(0.92, 0.92, 0.92, 1),
            background_normal="",
            color=THEME["fg"],
            font_size=14,
            **kwargs,
        )


class FeatureTextInput(TextInput):
    """普通版输入框。"""

    def __init__(self, **kwargs):
        super().__init__(
            background_color=(1, 1, 1, 1),
            foreground_color=THEME["fg"],
            cursor_color=THEME["accent"],
            font_size=14,
            padding=8,
            multiline=False,
            **kwargs,
        )


class MainLayout(ScrollView):
    """主界面，所有控件放在可滚动布局里。"""

    progress_value = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.clearcolor = THEME["bg"]
        self._build_ui()
        self._load_config()
        self._request_permissions()
        self._log_buffer = []
        Clock.schedule_interval(self._flush_logs, 0.3)
        self._start_time = None
        Clock.schedule_interval(self._tick_eta, 1.0)

    def _request_permissions(self):
        Clock.schedule_once(lambda dt: _request_android_permissions(), 0.5)

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", padding=10, spacing=8, size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))
        self.add_widget(root)

        root.add_widget(FeatureHeader())

        # 路径卡片
        path_card = FeatureCard()
        path_card.add_widget(Label(text="[b]游戏目录[/b]", markup=True, color=THEME["accent"], size_hint_y=None, height=24, halign="left"))
        path_card.add_widget(Label(text="选择 mods/plugins 所在文件夹", color=THEME["hint"], font_size=12, size_hint_y=None, height=20, halign="left"))
        in_box = BoxLayout(size_hint_y=None, height=46)
        self.input_path = FeatureTextInput(hint_text="例如 /sdcard/Download/mc-server", text="/sdcard/Download/mc-server")
        in_btn = FeatureButton(text="选择", variant="secondary", size_hint_x=None, width=80)
        in_btn.bind(on_release=lambda x: self._open_chooser(self.input_path, dirselect=True))
        in_box.add_widget(self.input_path)
        in_box.add_widget(in_btn)
        path_card.add_widget(in_box)

        path_card.add_widget(Label(text="[b]输出目录[/b]", markup=True, color=THEME["accent"], size_hint_y=None, height=24, halign="left"))
        out_box = BoxLayout(size_hint_y=None, height=46)
        self.output_path = FeatureTextInput(hint_text="输出位置", text="/sdcard/Download/mc-chinese-output")
        out_btn = FeatureButton(text="选择", variant="secondary", size_hint_x=None, width=80)
        out_btn.bind(on_release=lambda x: self._open_chooser(self.output_path, dirselect=True))
        out_box.add_widget(self.output_path)
        out_box.add_widget(out_btn)
        path_card.add_widget(out_box)
        root.add_widget(path_card)

        # 设置卡片
        settings_card = FeatureCard()
        settings_card.add_widget(Label(text="[b]翻译设置[/b]", markup=True, color=THEME["accent"], size_hint_y=None, height=24, halign="left"))

        settings_card.add_widget(Label(text="目标类型", color=THEME["hint"], size_hint_y=None, height=22, halign="left"))
        self.target_type = FeatureSpinner(
            text="模组",
            values=("模组", "插件", "整合包", "服务器"),
            size_hint_y=None,
            height=44,
        )
        settings_card.add_widget(self.target_type)

        settings_card.add_widget(Label(text="输出模式", color=THEME["hint"], size_hint_y=None, height=22, halign="left"))
        self.output_mode = FeatureSpinner(
            text="生成资源包/补丁",
            values=("生成资源包/补丁", "直接修改 jar"),
            size_hint_y=None,
            height=44,
        )
        settings_card.add_widget(self.output_mode)

        settings_card.add_widget(Label(text="翻译引擎", color=THEME["hint"], size_hint_y=None, height=22, halign="left"))
        self.engine = FeatureSpinner(
            text="多引擎自动切换",
            values=(
                "多引擎自动切换",
                "百度翻译",
                "有道翻译",
                "MyMemory",
                "LibreTranslate",
                "Linguee",
                "PONS",
                "Google",
                "LLM API",
            ),
            size_hint_y=None,
            height=44,
        )
        self.engine.bind(text=self._on_engine_change)
        settings_card.add_widget(self.engine)

        settings_card.add_widget(Label(text="翻译模式", color=THEME["hint"], size_hint_y=None, height=22, halign="left"))
        self.mode = FeatureSpinner(
            text="快速版",
            values=("快速版", "完整版"),
            size_hint_y=None,
            height=44,
        )
        settings_card.add_widget(self.mode)

        settings_card.add_widget(Label(text="请求延迟（秒）", color=THEME["hint"], size_hint_y=None, height=22, halign="left"))
        self.delay_input = FeatureTextInput(text="0.05", hint_text="0.05")
        settings_card.add_widget(self.delay_input)

        self.mode_hint = Label(
            text="[color=444444]输出模式：\n生成 → 模组生成 .zip 资源包，插件/整合包/服务器生成补丁/安装包\n直接修改 → 在原 jar 内写入汉化文件，并自动备份 .backup[/color]",
            markup=True,
            color=THEME["hint"],
            font_size=11,
            size_hint_y=None,
            height=60,
            halign="left",
            valign="top",
        )
        settings_card.add_widget(self.mode_hint)
        root.add_widget(settings_card)

        # API 配置卡片
        api_card = FeatureCard()
        api_card.add_widget(Label(text="[b]API 配置[/b]（仅 LLM API 需要）", markup=True, color=THEME["accent"], size_hint_y=None, height=24, halign="left"))
        self.api_key = FeatureTextInput(hint_text="API Key", password=True)
        api_card.add_widget(self.api_key)
        self.base_url = FeatureTextInput(hint_text="Base URL")
        api_card.add_widget(self.base_url)
        self.model = FeatureTextInput(hint_text="模型")
        api_card.add_widget(self.model)
        root.add_widget(api_card)

        # 操作卡片
        action_card = FeatureCard()
        action_card.add_widget(Label(text="[b]进度[/b]", markup=True, color=THEME["accent"], size_hint_y=None, height=24, halign="left"))

        self.progress_bar = ProgressBar(max=100, value=0, size_hint_y=None, height=24)
        self.progress_bar.color = THEME["gold"]
        action_card.add_widget(self.progress_bar)

        self.eta_label = Label(text="预计剩余时间：--", color=THEME["hint"], size_hint_y=None, height=22, halign="left")
        action_card.add_widget(self.eta_label)

        self.status_label = Label(text="状态：就绪", color=THEME["fg"], size_hint_y=None, height=24, halign="left")
        action_card.add_widget(self.status_label)

        self.start_btn = FeatureButton(text="开始翻译", variant="primary", size_hint_y=None, height=54)
        self.start_btn.bind(on_release=self._start)
        action_card.add_widget(self.start_btn)

        help_btn = FeatureButton(text="使用说明", variant="secondary", size_hint_y=None, height=44)
        help_btn.bind(on_release=self._show_help)
        action_card.add_widget(help_btn)
        root.add_widget(action_card)

        # 日志卡片
        log_card = FeatureCard()
        log_card.add_widget(Label(text="[b]运行日志[/b]", markup=True, color=THEME["accent"], size_hint_y=None, height=24, halign="left"))
        self.log_box = TextInput(
            readonly=True,
            multiline=True,
            background_color=(0.98, 0.98, 0.98, 1),
            foreground_color=THEME["fg"],
            font_size=12,
            size_hint_y=None,
            height=280,
        )
        log_card.add_widget(self.log_box)
        clear_btn = FeatureButton(text="清空日志", variant="secondary", size_hint_y=None, height=40)
        clear_btn.bind(on_release=lambda x: setattr(self.log_box, "text", ""))
        log_card.add_widget(clear_btn)
        root.add_widget(log_card)

        root.add_widget(Widget(size_hint_y=None, height=30))

    def _on_engine_change(self, spinner, text):
        if text == "LLM API":
            self._log("提示：选择 LLM API 后请填写 API Key、Base URL 和模型")

    def _open_chooser(self, target_input, dirselect=False):
        content = BoxLayout(orientation="vertical")
        default_path = target_input.text.strip() or "/sdcard/Download"
        try:
            if not Path(default_path).exists():
                default_path = "/sdcard/Download"
        except Exception:
            default_path = "/sdcard/Download"
        chooser = FileChooserListView(path=default_path, dirselect=dirselect)
        content.add_widget(chooser)
        btn_box = BoxLayout(size_hint_y=None, height=50, spacing=10)
        popup = Popup(title="选择目录" if dirselect else "选择文件", content=content, size_hint=(0.92, 0.85))

        def confirm(_):
            if chooser.selection:
                target_input.text = chooser.selection[0]
            popup.dismiss()

        cancel_btn = FeatureButton(text="取消", variant="secondary")
        cancel_btn.bind(on_release=popup.dismiss)
        ok_btn = FeatureButton(text="确定")
        ok_btn.bind(on_release=confirm)
        btn_box.add_widget(cancel_btn)
        btn_box.add_widget(ok_btn)
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
                eta = f"预计剩余时间：{remaining:.0f} 秒（已用 {elapsed:.0f} 秒）"
            elif remaining < 3600:
                eta = f"预计剩余时间：{remaining / 60:.1f} 分钟（已用 {elapsed / 60:.1f} 分钟）"
            else:
                eta = f"预计剩余时间：{remaining / 3600:.1f} 小时（已用 {elapsed / 3600:.1f} 小时）"
        else:
            eta = f"预计剩余时间：计算中...（已用 {elapsed:.0f} 秒）"
        self.eta_label.text = eta
        return True

    def _load_config(self):
        try:
            if CONFIG_FILE.exists():
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.input_path.text = cfg.get("input", "/sdcard/Download/mc-server")
                self.output_path.text = cfg.get("output", "/sdcard/Download/mc-chinese-output")
                self.target_type.text = cfg.get("target_type", "模组")
                self.output_mode.text = cfg.get("output_mode", "生成资源包/补丁")
                self.engine.text = cfg.get("engine", "多引擎自动切换")
                self.mode.text = cfg.get("mode", "快速版")
                self.delay_input.text = cfg.get("delay", "0.05")
                self.api_key.text = cfg.get("api_key", "")
                self.base_url.text = cfg.get("base_url", "")
                self.model.text = cfg.get("model", "")
        except Exception:
            pass

    def _save_config(self):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            cfg = {
                "input": self.input_path.text,
                "output": self.output_path.text,
                "target_type": self.target_type.text,
                "output_mode": self.output_mode.text,
                "engine": self.engine.text,
                "mode": self.mode.text,
                "delay": self.delay_input.text,
                "api_key": self.api_key.text,
                "base_url": self.base_url.text,
                "model": self.model.text,
            }
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"保存配置失败：{exc}")

    def _engine_map(self) -> str:
        mapping = {
            "多引擎自动切换": "multi_free",
            "百度翻译": "baidu_free",
            "有道翻译": "youdao_free",
            "MyMemory": "mymemory",
            "LibreTranslate": "libre",
            "Linguee": "linguee",
            "PONS": "pons",
            "Google": "google_free",
            "LLM API": "llm",
        }
        return mapping.get(self.engine.text, "multi_free")

    def _target_map(self) -> str:
        mapping = {"模组": "mods", "插件": "plugins", "整合包": "modpack", "服务器": "server"}
        return mapping.get(self.target_type.text, "mods")

    def _output_mode_map(self) -> str:
        mapping = {"生成资源包/补丁": "generate", "直接修改 jar": "inplace"}
        return mapping.get(self.output_mode.text, "generate")

    def _start(self, _):
        input_path = Path(self.input_path.text.strip())
        output_path = Path(self.output_path.text.strip())
        target = self._target_map()
        output_mode = self._output_mode_map()
        engine_name = self._engine_map()
        mode = "full" if self.mode.text == "完整版" else "fast"
        api_key = self.api_key.text.strip() or None
        base_url = self.base_url.text.strip() or None
        model = self.model.text.strip() or "deepseek-chat"
        try:
            delay = float(self.delay_input.text.strip() or "0.05")
        except ValueError:
            delay = 0.05

        if not input_path.exists():
            self._log("错误：输入目录不存在，请检查路径或授权存储权限")
            return

        if engine_name == "llm" and not api_key:
            self._log("错误：选择 LLM API 时必须填写 API Key")
            return

        self.start_btn.disabled = True
        self.start_btn.text = "翻译中..."
        self.status_label.text = "状态：正在翻译..."
        self.progress_bar.value = 0
        self.eta_label.text = "预计剩余时间：计算中..."
        self._start_time = time.time()
        self._save_config()
        self._log("=" * 30)
        self._log(f"开始翻译 | 目标：{self.target_type.text} | 输出：{self.output_mode.text} | 引擎：{self.engine.text} | 模式：{self.mode.text}")

        thread = threading.Thread(
            target=self._worker,
            args=(input_path, output_path, target, output_mode, engine_name, mode, api_key, base_url, model, delay),
            daemon=True,
        )
        thread.start()

    def _worker(self, input_path, output_path, target, output_mode, engine_name, mode, api_key, base_url, model, delay):
        try:
            translator = Translator(
                engine=engine_name,
                api_key=api_key,
                base_url=base_url,
                model=model,
                mode=mode,
                delay=delay,
            )
            self._log(translator.readiness_message())

            if not translator.is_ready():
                self._log("翻译引擎未就绪，请检查网络或 API Key")
                return

            output_path.mkdir(parents=True, exist_ok=True)

            def progress_cb(current: int, total: int, msg: str = ""):
                pct = (current / total * 100) if total > 0 else 0
                self._set_progress(pct)
                if msg:
                    self._log(msg)

            if target == "modpack":
                self._log("处理整合包：mods 生成资源包，plugins 生成汉化补丁")
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
                    f"统计：共 {stats['total']} 个 jar，"
                    f"翻译 {stats['translated_mods']} 个，"
                    f"跳过 {stats['skipped_mods']} 个，"
                    f"失败 {stats['errors']} 个，"
                    f"总条目 {stats['total_entries']}"
                )
            elif target == "server":
                self._log("处理服务器：自动扫描 mods + plugins")
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
                if output_mode == "inplace":
                    self._log(
                        f"服务器文件已直接修改（原 jar 已备份为 .backup）\n"
                        f"统计：共 {stats['total']} 个 jar，"
                        f"翻译 {stats['translated_mods']} 个，"
                        f"跳过 {stats['skipped_mods']} 个，"
                        f"失败 {stats['errors']} 个，"
                        f"总条目 {stats['total_entries']}"
                    )
                else:
                    server_zip = output_path / "ServerChinesePack.zip"
                    self._log(
                        f"服务器汉化安装包已生成：{server_zip}\n"
                        f"统计：共 {stats['total']} 个 jar，"
                        f"翻译 {stats['translated_mods']} 个，"
                        f"跳过 {stats['skipped_mods']} 个，"
                        f"失败 {stats['errors']} 个，"
                        f"总条目 {stats['total_entries']}"
                    )
            elif target == "plugins":
                plugins_dir = discover_target_dir(input_path, "plugins")
                jars = scan_jars(plugins_dir)
                self._log(f"扫描到 {len(jars)} 个插件 jar")
                if not jars:
                    self._log("未找到插件 jar，请检查路径是否正确")
                    return
                if output_mode == "inplace":
                    presult = []
                    for idx, jar in enumerate(jars):
                        presult.append(process_plugin_jar_inplace(jar, translator, backup=True, on_log=lambda m: self._log(m)))
                        progress_cb(idx + 1, len(jars), f"直接修改插件 {jar.name}")
                else:
                    presult = generate_plugin_patch(jars, translator, output_path, on_log=lambda m: self._log(m), progress_cb=progress_cb)
                stats = summarize(presult)
                patch_zip = output_path / "AutoChinesePluginPatch.zip"
                self._log(
                    f"汉化补丁已生成：{patch_zip}\n"
                    f"统计：共 {stats['total']} 个插件，"
                    f"翻译 {stats['translated_mods']} 个，"
                    f"跳过 {stats['skipped_mods']} 个，"
                    f"失败 {stats['errors']} 个，"
                    f"总条目 {stats['total_entries']}"
                )
            else:
                mods_dir = discover_target_dir(input_path, "mods")
                jars = scan_jars(mods_dir)
                self._log(f"扫描到 {len(jars)} 个模组 jar")
                if not jars:
                    self._log("未找到模组 jar，请检查路径是否正确")
                    return
                if output_mode == "inplace":
                    mresult = []
                    for idx, jar in enumerate(jars):
                        mresult.append(process_jar_inplace(jar, translator, backup=True, on_log=lambda m: self._log(m)))
                        progress_cb(idx + 1, len(jars), f"直接修改模组 {jar.name}")
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
                self._log(
                    f"资源包已生成：{output_path / 'AutoChineseResourcePack.zip'}\n"
                    f"统计：共 {stats['total']} 个模组，"
                    f"翻译 {stats['translated_mods']} 个，"
                    f"跳过 {stats['skipped_mods']} 个，"
                    f"失败 {stats['errors']} 个，"
                    f"总条目 {stats['total_entries']}"
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

    def _show_help(self, _):
        content = ScrollView()
        help_label = Label(
            text=(
                "使用说明：\n\n"
                "1. 将整合包/服务器文件夹复制到手机存储（如 /sdcard/Download/mc-server）。\n"
                "2. 在「游戏目录」选择该文件夹。\n"
                "3. 选择目标类型：模组 / 插件 / 整合包 / 服务器。\n"
                "4. 选择输出模式：\n"
                "   · 生成资源包/补丁：安全，生成 .zip 安装包或补丁文件。\n"
                "   · 直接修改 jar：直接改原 jar，并自动备份 .backup。\n"
                "5. 选择翻译引擎。没有 API Key 就选「多引擎自动切换」或「百度/有道」。\n"
                "6. 点击「开始翻译」，等待进度条走到 100%。\n\n"
                "注意事项：\n"
                "· 首次使用请允许存储权限。\n"
                "· 安卓 11+ 若无法直接访问 /sdcard，请用系统文件管理器将文件放到 Download 目录。\n"
                "· 免费引擎较慢，建议用 DeepSeek/硅基流动 API。\n"
                "· 生成结果在输出目录：模组是 .zip 资源包，插件是 plugin_patch 文件夹，\n"
                "  服务器是 ServerChinesePack.zip 安装包；直接修改则保留在原目录。"
            ),
            color=THEME["fg"],
            font_size=14,
            size_hint_y=None,
            text_size=(None, None),
            halign="left",
            valign="top",
            padding=(12, 12),
        )
        help_label.bind(width=lambda obj, w: setattr(help_label, "text_size", (w, None)))
        help_label.bind(texture_size=lambda obj, size: setattr(help_label, "height", size[1]))
        content.add_widget(help_label)
        popup = Popup(title="使用说明", content=content, size_hint=(0.92, 0.85))
        popup.open()


class MCChineseApp(App):
    def build(self):
        return MainLayout()


if __name__ == "__main__":
    MCChineseApp().run()
