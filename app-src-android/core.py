#!/usr/bin/env python3
"""Minecraft 模组 / 插件 / 整合包中文化核心逻辑"""

import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import yaml

from translate import Translator


@dataclass
class TargetInfo:
    path: Path
    target_type: str = "mod"  # mod / plugin
    modid: Optional[str] = None
    lang_files: List[Tuple[str, str]] = field(default_factory=list)
    translated_count: int = 0
    skipped: bool = True
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 路径与扫描
# ---------------------------------------------------------------------------

# 模组语言文件模式
MOD_LANG_PATTERNS = [
    re.compile(r"^assets/([^/]+)/lang/en_us\.json$", re.IGNORECASE),
    re.compile(r"^assets/([^/]+)/lang/en_gb\.json$", re.IGNORECASE),
    re.compile(r"^assets/([^/]+)/lang/en_us\.lang$", re.IGNORECASE),
    re.compile(r"^assets/([^/]+)/lang/en_gb\.lang$", re.IGNORECASE),
]

# 插件语言文件模式（按常见程度排序）
PLUGIN_LANG_PATTERNS = [
    re.compile(r"^lang/en_us\.yml$", re.IGNORECASE),
    re.compile(r"^lang/en_us\.json$", re.IGNORECASE),
    re.compile(r"^lang/en_US\.yml$", re.IGNORECASE),
    re.compile(r"^lang/en_US\.json$", re.IGNORECASE),
    re.compile(r"^languages/en_US\.yml$", re.IGNORECASE),
    re.compile(r"^languages/en_US\.json$", re.IGNORECASE),
    re.compile(r"^language/en_US\.yml$", re.IGNORECASE),
    re.compile(r"^language/en_US\.json$", re.IGNORECASE),
    re.compile(r"^i18n/en_us\.yml$", re.IGNORECASE),
    re.compile(r"^.*/lang/en_us\.yml$", re.IGNORECASE),
    re.compile(r"^.*/lang/en_us\.json$", re.IGNORECASE),
]

# 需要排除的二进制/资源目录
SKIP_DIRS = {
    "META-INF", "assets", "data", "textures", "models", "sounds", "shaders",
    "lang"  # 插件的 lang 目录会单独匹配，但扫描文件内容时跳过
}


def _is_path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def discover_target_dir(minecraft_path: Path, target_type: str) -> Path:
    """
    根据传入的 Minecraft 根目录和目标类型，定位 mods 或 plugins 文件夹。
    target_type: "mods" | "plugins"
    """
    folder = "mods" if target_type == "mods" else "plugins"\n    # 如果用户已经选中了 mods/plugins 目录本身，直接返回\n    if minecraft_path.name.lower() == folder.lower():\n        return minecraft_path

    candidates = [\n        minecraft_path / folder,\n        minecraft_path / ".minecraft" / folder,\n        minecraft_path.parent / ".minecraft" / folder,\n        # 常见启动器目录结构\n        minecraft_path / "minecraft" / folder,\n        minecraft_path.parent / folder,\n        # FCL / Fold Craft Launcher\n        minecraft_path / "Android" / "data" / "com.tungsten.fcl" / "files" / ".minecraft" / folder,\n        minecraft_path.parent / "Android" / "data" / "com.tungsten.fcl" / "files" / ".minecraft" / folder,\n        # 我的世界 Mio 启动器\n        minecraft_path / "Android" / "data" / "com.mio.launcher" / "files" / ".minecraft" / folder,\n        minecraft_path.parent / "Android" / "data" / "com.mio.launcher" / "files" / ".minecraft" / folder,\n        # HMCL-PE\n        minecraft_path / "Android" / "data" / "com.tungsten.hmclpe" / "files" / ".minecraft" / folder,\n        minecraft_path.parent / "Android" / "data" / "com.tungsten.hmclpe" / "files" / ".minecraft" / folder,\n        # PojavLauncher\n        minecraft_path / "Android" / "data" / "net.kdt.pojavlaunch" / "files" / ".minecraft" / folder,\n        minecraft_path.parent / "Android" / "data" / "net.kdt.pojavlaunch" / "files" / ".minecraft" / folder,\n        # 部分启动器把 minecraft 目录放在游戏根目录\n        minecraft_path / "games" / "com.mojang" / folder,\n        minecraft_path.parent / "games" / "com.mojang" / folder,\n    ]\n    for c in candidates:\n        if c.exists() and c.is_dir():\n            return c

    # 兜底：在输入目录下搜索最多三级深度的目标文件夹\n    try:\n        for depth in range(1, 4):\n            pattern = "/".join(["*"] * depth) + f"/{folder}"\n            for found in minecraft_path.rglob(pattern):\n                if found.is_dir():\n                    return found\n    except Exception:\n        pass

    return minecraft_path / folder


def scan_jars(target_dir: Path, on_log: Optional[Callable[[str], None]] = None) -> List[Path]:\n    """扫描目标目录下所有 jar 文件。"""\n    log = on_log or (lambda x: None)\n    if not target_dir.exists():\n        log(f"扫描目录不存在：{target_dir}")\n        log("请检查输入路径是否正确，或是否已授予存储权限")\n        return []\n    try:\n        items = list(target_dir.iterdir())\n    except PermissionError as exc:\n        log(f"读取目录失败（无权限）：{target_dir}")\n        log("Android 11+ 需要“所有文件访问权限”才能读取该目录，请到系统设置中开启")\n        return []\n    except Exception as exc:\n        log(f"读取目录失败：{target_dir}，错误：{exc}")\n        return []\n    jar_files = [p for p in items if p.suffix.lower() == ".jar"]\n    log(f"目录 {target_dir} 下共 {len(items)} 个文件/文件夹，其中 jar 文件 {len(jar_files)} 个")\n    if not jar_files and items:\n        sample = ", ".join(p.name for p in items[:8])\n        log(f"该目录下非 jar 文件示例：{sample}")\n        log("提示：如果这里应该是 mods/plugins 目录，请确认是否选错了父目录")\n    return sorted(jar_files)


# 整合包 / 服务器 / 插件相关函数保持原样...\n# [以下省略大量未改动代码，实际替换时请保留原 translate.py 等依赖]\n[PASTE_CONTENT_END]
