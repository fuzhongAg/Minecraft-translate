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
    re.compile(r"^locale/en_US\.yml$", re.IGNORECASE),
    re.compile(r"^locale/en_US\.json$", re.IGNORECASE),
    re.compile(r"^i18n/en_US\.yml$", re.IGNORECASE),
    re.compile(r"^i18n/en_US\.json$", re.IGNORECASE),
]


def discover_target_dir(minecraft_path: Path, target_type: str) -> Path:
    """
    根据传入的 Minecraft 根目录和目标类型，定位 mods 或 plugins 文件夹。
    target_type: "mods" | "plugins"
    """
    folder = "mods" if target_type == "mods" else "plugins"
    candidates = [
        minecraft_path / folder,
        minecraft_path / ".minecraft" / folder,
        minecraft_path.parent / ".minecraft" / folder,
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    return minecraft_path / folder


def discover_mods(minecraft_path: Path) -> Path:
    """兼容旧接口：定位 mods 文件夹。"""
    return discover_target_dir(minecraft_path, "mods")


def discover_plugins(minecraft_path: Path) -> Path:
    """定位 plugins 文件夹。"""
    return discover_target_dir(minecraft_path, "plugins")


def scan_jars(target_dir: Path) -> List[Path]:
    """扫描目标目录下所有 jar 文件。"""
    if not target_dir.exists():
        return []
    return sorted([p for p in target_dir.iterdir() if p.suffix.lower() == ".jar"])


def scan_mod_jars(mods_dir: Path) -> List[Path]:
    """兼容旧接口。"""
    return scan_jars(mods_dir)


def scan_plugin_jars(plugins_dir: Path) -> List[Path]:
    """扫描 plugins 目录。"""
    return scan_jars(plugins_dir)


# ---------------------------------------------------------------------------
# 通用翻译辅助
# ---------------------------------------------------------------------------

# 颜色代码与占位符保留
COLOR_CODE_RE = re.compile(r"([&§][0-9a-fA-Fk-oK-OrR])")
PLACEHOLDER_RE = re.compile(r"(%[\w._-]+%|\{[^{}]+\}|<[^<>]+>|%\w+|%\d+\$?[sdofxX])")
# 看起来像是代码/权限/命令的值，跳过不翻译
SKIP_VALUE_RE = re.compile(
    r"^([\w.]+\.)+[\w.]+$|"           # 权限节点
    r"^/[\w ]+$|"                       # 命令
    r"^(https?|ftp)://\S+$|"            # URL
    r"^[\d\W]+$"                        # 纯数字/符号
)


def _is_translatable(text: str) -> bool:
    """判断一个字符串值是否值得翻译。"""
    if not text or len(text.strip()) < 2:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return False  # 已有中文
    if SKIP_VALUE_RE.match(text.strip()):
        return False
    return True


def _protect_codes(text: str) -> Tuple[str, List[str]]:
    """保护颜色代码与占位符，返回替换后的文本和 token 列表。"""
    tokens: List[str] = []

    def replace(m):
        tokens.append(m.group(0))
        return f"@@{len(tokens) - 1}@@"

    protected = PLACEHOLDER_RE.sub(replace, text)
    protected = COLOR_CODE_RE.sub(replace, protected)
    return protected, tokens


def _restore_codes(text: str, tokens: List[str]) -> str:
    """恢复保护的颜色代码与占位符。"""
    for i, token in enumerate(tokens):
        text = text.replace(f"@@{i}@@", token)
    return text


def _translate_value(
    value: str,
    translator: Translator,
    on_update: Optional[Callable[[str], None]] = None,
) -> Tuple[str, bool]:
    """翻译单个字符串值，返回（翻译后文本，是否真正翻译）。"""
    if not _is_translatable(value):
        return value, False

    protected, tokens = _protect_codes(value)
    try:
        res = translator.translate(protected)
        restored = _restore_codes(res.text, tokens)
        if on_update:
            on_update(f"  └ {value[:50]} -> {restored[:50]}")
        return restored, not res.cached
    except Exception as exc:
        if on_update:
            on_update(f"  └ 翻译失败（{exc}），保留原文: {value[:50]}")
        return value, False


def _translate_nested(
    data: Union[Dict, List],
    translator: Translator,
    on_update: Optional[Callable[[str], None]] = None,
) -> Tuple[Union[Dict, List], int]:
    """递归翻译 dict/list 中的字符串值。"""
    translated = 0
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if isinstance(v, str):
                new_v, was_translated = _translate_value(v, translator, on_update)
                out[k] = new_v
                if was_translated:
                    translated += 1
            elif isinstance(v, (dict, list)):
                out[k], count = _translate_nested(v, translator, on_update)
                translated += count
            else:
                out[k] = v
        return out, translated
    elif isinstance(data, list):
        out = []
        for item in data:
            if isinstance(item, str):
                new_item, was_translated = _translate_value(item, translator, on_update)
                out.append(new_item)
                if was_translated:
                    translated += 1
            elif isinstance(item, (dict, list)):
                new_item, count = _translate_nested(item, translator, on_update)
                out.append(new_item)
                translated += count
            else:
                out.append(item)
        return out, translated
    return data, 0


# ---------------------------------------------------------------------------
# 模组处理（保持原有逻辑）
# ---------------------------------------------------------------------------

def _detect_format_lang(content: str) -> Dict[str, str]:
    """解析旧版 .lang 文件为键值对。"""
    result: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _serialize_lang(data: Dict[str, str]) -> str:
    """将键值对序列化为旧版 .lang 格式。"""
    lines = ["# Generated by mc-mod-auto-chinese", ""]
    for k, v in data.items():
        lines.append(f"{k}={v}")
    return "\n".join(lines)


def _translate_flat_dict(
    data: Dict[str, str],
    translator: Translator,
    on_update: Optional[Callable[[str], None]] = None,
) -> Tuple[Dict[str, str], int]:
    """翻译扁平 dict（用于 .json / .lang）。"""
    translated = 0
    out: Dict[str, str] = {}
    for key, value in data.items():
        if not value or re.search(r"[\u4e00-\u9fff]", value):
            out[key] = value
            continue
        protected, tokens = _protect_codes(value)
        try:
            res = translator.translate(protected)
            out[key] = _restore_codes(res.text, tokens)
            if not res.cached:
                translated += 1
            if on_update:
                on_update(f"  └ {key}: {value[:40]} -> {out[key][:40]}")
        except Exception as exc:
            out[key] = value
            if on_update:
                on_update(f"  └ {key}: 翻译失败（{exc}），保留原文")
    return out, translated


def _mod_target_path(en_path: str) -> str:
    """将 en_us.* 路径替换为 zh_cn.*。"""
    return re.sub(r"en_(us|gb)(\.json|\.lang)$", r"zh_cn\2", en_path, flags=re.IGNORECASE)


def process_jar_inplace(
    jar_path: Path,
    translator: Translator,
    backup: bool = True,
    on_log: Optional[Callable[[str], None]] = None,
) -> TargetInfo:
    """直接修改 mod jar 文件，并可选备份原文件。"""
    info = TargetInfo(path=jar_path, target_type="mod")
    log = on_log or (lambda x: None)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backup_path = jar_path.with_suffix(jar_path.suffix + ".backup")
            if backup and not backup_path.exists():
                shutil.copy2(jar_path, backup_path)
                log(f"已备份: {backup_path.name}")

            with zipfile.ZipFile(jar_path, "r") as zin:
                items = zin.infolist()
                for item in items:
                    zin.extract(item, tmp)

                modified = False
                for item in items:
                    arcname = item.filename.replace("\\", "/")
                    for pat in MOD_LANG_PATTERNS:
                        m = pat.match(arcname)
                        if not m:
                            continue
                        modid = m.group(1)
                        info.modid = modid
                        target = _mod_target_path(arcname)
                        if target in [i.filename for i in items]:
                            log(f"已存在 {target}，跳过")
                            info.skipped = True
                            continue

                        raw = zin.read(item).decode("utf-8", errors="ignore")
                        if arcname.lower().endswith(".json"):
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError:
                                log(f"JSON 解析失败: {arcname}")
                                continue
                            new_data, count = _translate_flat_dict(data, translator, on_update=log)
                            out_bytes = json.dumps(
                                new_data, ensure_ascii=False, indent=2
                            ).encode("utf-8")
                        else:
                            data = _detect_format_lang(raw)
                            new_data, count = _translate_flat_dict(data, translator, on_update=log)
                            out_bytes = _serialize_lang(new_data).encode("utf-8")

                        out_path = tmp / target
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_bytes(out_bytes)
                        info.translated_count += count
                        info.lang_files.append((arcname, target))
                        info.skipped = False
                        modified = True
                        log(f"已生成: {target} ({count} 条新翻译)")
                        break

                if not modified:
                    log(f"未发现英文语言文件: {jar_path.name}")
                    return info

            tmp_jar = tmp / (jar_path.name + ".tmp")
            with zipfile.ZipFile(tmp_jar, "w", zipfile.ZIP_DEFLATED) as zout:
                for file in tmp.rglob("*"):
                    if file.is_file():
                        arcname = str(file.relative_to(tmp)).replace("\\", "/")
                        zout.write(file, arcname)
            shutil.move(str(tmp_jar), str(jar_path))
    except Exception as exc:
        info.error = str(exc)
        log(f"处理失败 {jar_path.name}: {exc}")
    return info


def generate_resource_pack(
    jar_paths: List[Path],
    translator: Translator,
    output_dir: Path,
    pack_name: str = "AutoChineseResourcePack",
    pack_format: int = 15,
    on_log: Optional[Callable[[str], None]] = None,
    skip_existing_zh: bool = True,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> List[TargetInfo]:
    """不修改原 mod jar，而是生成一个 Minecraft 资源包。"""
    log = on_log or (lambda x: None)
    progress = progress_cb or (lambda c, t, m: None)
    results: List[TargetInfo] = []
    total = len(jar_paths)

    pack_root = output_dir / pack_name
    assets_dir = pack_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    mcmeta = {
        "pack": {
            "pack_format": pack_format,
            "description": "Auto-generated Chinese translation by mc-mod-auto-chinese",
        }
    }
    (pack_root / "pack.mcmeta").write_text(
        json.dumps(mcmeta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for idx, jar_path in enumerate(jar_paths, 1):
        progress(idx, total, f"处理模组 {jar_path.name} ({idx}/{total})")
        info = TargetInfo(path=jar_path, target_type="mod")
        try:
            with zipfile.ZipFile(jar_path, "r") as zin:
                all_names = [i.filename.replace("\\", "/") for i in zin.infolist()]
                for item in zin.infolist():
                    arcname = item.filename.replace("\\", "/")
                    for pat in MOD_LANG_PATTERNS:
                        m = pat.match(arcname)
                        if not m:
                            continue
                        modid = m.group(1)
                        info.modid = modid
                        target = _mod_target_path(arcname)
                        if skip_existing_zh and target in all_names:
                            log(f"[{jar_path.name}] 已存在 {target}，跳过")
                            info.skipped = True
                            continue

                        raw = zin.read(item).decode("utf-8", errors="ignore")
                        if arcname.lower().endswith(".json"):
                            data = json.loads(raw)
                            new_data, count = _translate_flat_dict(data, translator, on_update=log)
                            out_bytes = json.dumps(
                                new_data, ensure_ascii=False, indent=2
                            ).encode("utf-8")
                        else:
                            data = _detect_format_lang(raw)
                            new_data, count = _translate_flat_dict(data, translator, on_update=log)
                            out_bytes = _serialize_lang(new_data).encode("utf-8")

                        out_path = assets_dir / modid / "lang" / Path(target).name
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_bytes(out_bytes)
                        info.translated_count += count
                        info.lang_files.append((arcname, str(out_path)))
                        info.skipped = False
                        log(f"[{jar_path.name}] {target} -> {count} 条")
                        break
        except Exception as exc:
            info.error = str(exc)
            log(f"处理失败 {jar_path.name}: {exc}")
        results.append(info)

    zip_path = output_dir / f"{pack_name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in pack_root.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(pack_root))
    log(f"资源包已生成: {zip_path}")
    return results


# ---------------------------------------------------------------------------
# 插件处理
# ---------------------------------------------------------------------------

def _plugin_target_path(en_path: str) -> str:
    """将 en_US/en_us 路径替换为 zh_CN/zh_cn。"""
    # 例如 lang/en_us.yml -> lang/zh_CN.yml
    return re.sub(r"en[_-](us|US)(\.ya?ml|\.json)$", r"zh_CN\2", en_path, flags=re.IGNORECASE)


def _safe_yaml_load(raw: str) -> Optional[Union[Dict, List]]:
    """安全加载 YAML，失败后返回 None。"""
    try:
        return yaml.safe_load(raw)
    except Exception:
        return None


def _safe_yaml_dump(data: Union[Dict, List]) -> str:
    """保持 YAML 格式稳定输出。"""
    # default_flow_style=False 保持块格式；allow_unicode=True 允许中文；sort_keys=False 保持原顺序
    return yaml.safe_dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=4096,
    )


def process_plugin_jar_inplace(
    jar_path: Path,
    translator: Translator,
    backup: bool = True,
    on_log: Optional[Callable[[str], None]] = None,
) -> TargetInfo:
    """
    直接修改插件 jar 文件，并可选备份原文件。
    只翻译明显的语言文件，绝不碰 plugin.yml。
    """
    info = TargetInfo(path=jar_path, target_type="plugin")
    log = on_log or (lambda x: None)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            backup_path = jar_path.with_suffix(jar_path.suffix + ".backup")
            if backup and not backup_path.exists():
                shutil.copy2(jar_path, backup_path)
                log(f"已备份: {backup_path.name}")

            with zipfile.ZipFile(jar_path, "r") as zin:
                items = zin.infolist()
                for item in items:
                    # 跳过 plugin.yml 与 plugin 目录下的 plugin.yml，绝对不翻译
                    lower_name = item.filename.replace("\\", "/").lower()
                    if lower_name.endswith("plugin.yml"):
                        continue
                    zin.extract(item, tmp)

                modified = False
                for item in items:
                    arcname = item.filename.replace("\\", "/")
                    lower_arc = arcname.lower()
                    # 安全跳过 plugin.yml
                    if lower_arc.endswith("plugin.yml"):
                        continue

                    matched = False
                    for pat in PLUGIN_LANG_PATTERNS:
                        if pat.match(arcname):
                            matched = True
                            break
                    if not matched:
                        continue

                    target = _plugin_target_path(arcname)
                    if target in [i.filename.replace("\\", "/") for i in items]:
                        log(f"已存在 {target}，跳过")
                        info.skipped = True
                        continue

                    raw = zin.read(item).decode("utf-8", errors="ignore")
                    count = 0
                    if arcname.lower().endswith(".json"):
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            log(f"JSON 解析失败: {arcname}")
                            continue
                        new_data, count = _translate_nested(data, translator, on_update=log)
                        out_bytes = json.dumps(new_data, ensure_ascii=False, indent=2).encode("utf-8")
                    else:
                        data = _safe_yaml_load(raw)
                        if data is None:
                            log(f"YAML 解析失败: {arcname}")
                            continue
                        new_data, count = _translate_nested(data, translator, on_update=log)
                        out_bytes = _safe_yaml_dump(new_data).encode("utf-8")

                    out_path = tmp / target
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(out_bytes)
                    info.translated_count += count
                    info.lang_files.append((arcname, target))
                    info.skipped = False
                    modified = True
                    log(f"已生成: {target} ({count} 条新翻译)")

                if not modified:
                    log(f"未发现英文语言文件: {jar_path.name}")
                    return info

            tmp_jar = tmp / (jar_path.name + ".tmp")
            with zipfile.ZipFile(tmp_jar, "w", zipfile.ZIP_DEFLATED) as zout:
                for file in tmp.rglob("*"):
                    if file.is_file():
                        arcname = str(file.relative_to(tmp)).replace("\\", "/")
                        zout.write(file, arcname)
            shutil.move(str(tmp_jar), str(jar_path))
    except Exception as exc:
        info.error = str(exc)
        log(f"处理失败 {jar_path.name}: {exc}")
    return info


def generate_plugin_patch(
    jar_paths: List[Path],
    translator: Translator,
    output_dir: Path,
    on_log: Optional[Callable[[str], None]] = None,
    skip_existing_zh: bool = True,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> List[TargetInfo]:
    """
    不修改原插件 jar，而是生成一个汉化补丁目录。
    用户可将补丁解压后覆盖到 plugins 文件夹使用。
    """
    log = on_log or (lambda x: None)
    progress = progress_cb or (lambda c, t, m: None)
    results: List[TargetInfo] = []
    total = len(jar_paths)
    patch_root = output_dir / "AutoChinesePluginPatch"

    for idx, jar_path in enumerate(jar_paths, 1):
        progress(idx, total, f"处理插件 {jar_path.name} ({idx}/{total})")
        info = TargetInfo(path=jar_path, target_type="plugin")
        try:
            with zipfile.ZipFile(jar_path, "r") as zin:
                all_names = [i.filename.replace("\\", "/") for i in zin.infolist()]
                for item in zin.infolist():
                    arcname = item.filename.replace("\\", "/")
                    matched = False
                    for pat in PLUGIN_LANG_PATTERNS:
                        if pat.match(arcname):
                            matched = True
                            break
                    if not matched:
                        continue

                    target = _plugin_target_path(arcname)
                    if skip_existing_zh and target in all_names:
                        log(f"[{jar_path.name}] 已存在 {target}，跳过")
                        info.skipped = True
                        continue

                    raw = zin.read(item).decode("utf-8", errors="ignore")
                    if arcname.lower().endswith(".json"):
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            log(f"JSON 解析失败: {arcname}")
                            continue
                        new_data, count = _translate_nested(data, translator, on_update=log)
                        out_bytes = json.dumps(new_data, ensure_ascii=False, indent=2).encode("utf-8")
                    else:
                        data = _safe_yaml_load(raw)
                        if data is None:
                            log(f"YAML 解析失败: {arcname}")
                            continue
                        new_data, count = _translate_nested(data, translator, on_update=log)
                        out_bytes = _safe_yaml_dump(new_data).encode("utf-8")

                    # 补丁路径保持 jar 内部结构，放到 jar 同名文件夹下
                    out_path = patch_root / jar_path.stem / target
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(out_bytes)
                    info.translated_count += count
                    info.lang_files.append((arcname, str(out_path)))
                    info.skipped = False
                    log(f"[{jar_path.name}] {target} -> {count} 条")
                    break
        except Exception as exc:
            info.error = str(exc)
            log(f"处理失败 {jar_path.name}: {exc}")
        results.append(info)

    # 打包成 zip 方便分发
    zip_path = output_dir / "AutoChinesePluginPatch.zip"
    if patch_root.exists() and any(patch_root.iterdir()):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in patch_root.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(patch_root))
        log(f"插件汉化补丁已生成: {zip_path}")
    return results


# ---------------------------------------------------------------------------
# 整合包处理：同时处理 mods 与 plugins
# ---------------------------------------------------------------------------

def process_modpack(
    minecraft_path: Path,
    translator: Translator,
    output_dir: Path,
    pack_format: int = 15,
    on_log: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    mode: str = "generate",
) -> List[TargetInfo]:
    """
    处理整合包：
      - mode="generate"：mods 生成资源包，plugins 生成汉化补丁
      - mode="inplace"：直接修改 mods/plugins 里的 jar（自动备份）
    """
    log = on_log or (lambda x: None)
    progress = progress_cb or (lambda c, t, m: None)
    results: List[TargetInfo] = []

    def _count() -> int:
        return sum(1 for r in results if r.translated_count > 0)

    mods_dir = discover_target_dir(minecraft_path, "mods")
    if mods_dir.exists():
        log(f"检测到 mods 目录：{mods_dir}")
        mod_jars = scan_jars(mods_dir)
        if mod_jars:
            log(f"开始处理 {len(mod_jars)} 个模组...")
            if mode == "inplace":
                for idx, jar in enumerate(mod_jars):
                    results.append(
                        process_jar_inplace(jar, translator, backup=True, on_log=on_log)
                    )
                    progress(idx + 1, len(mod_jars), f"直接修改模组 {jar.name}")
            else:
                results.extend(
                    generate_resource_pack(
                        mod_jars,
                        translator,
                        output_dir=output_dir,
                        pack_format=pack_format,
                        on_log=on_log,
                        progress_cb=lambda c, t, m: progress(c, t, f"[模组] {m}"),
                    )
                )

    plugins_dir = discover_target_dir(minecraft_path, "plugins")
    if plugins_dir.exists():
        log(f"检测到 plugins 目录：{plugins_dir}")
        plugin_jars = scan_jars(plugins_dir)
        if plugin_jars:
            log(f"开始处理 {len(plugin_jars)} 个插件...")
            if mode == "inplace":
                for idx, jar in enumerate(plugin_jars):
                    results.append(
                        process_plugin_jar_inplace(
                            jar, translator, backup=True, on_log=on_log
                        )
                    )
                    progress(
                        len(mod_jars or []) + idx + 1,
                        len(mod_jars or []) + len(plugin_jars),
                        f"直接修改插件 {jar.name}",
                    )
            else:
                results.extend(
                    generate_plugin_patch(
                        plugin_jars,
                        translator,
                        output_dir=output_dir,
                        on_log=on_log,
                        progress_cb=lambda c, t, m: progress(c, t, f"[插件] {m}"),
                    )
                )

    if not results:
        log("未找到 mods 或 plugins 目录")
    return results


# ---------------------------------------------------------------------------
# 服务器处理：生成可直接解压到服务器根目录的安装包
# ---------------------------------------------------------------------------

def process_server(
    server_root: Path,
    translator: Translator,
    output_dir: Path,
    pack_format: int = 15,
    on_log: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    mode: str = "generate",
) -> List[TargetInfo]:
    """
    处理 Minecraft 服务器目录：
      - mode="generate"：扫描 mods/ 与 plugins/，生成资源包/汉化补丁并打包为 ServerChinesePack.zip
      - mode="inplace"：直接修改服务器内的 mods/ 与 plugins/ 里的 jar（自动备份）
    """
    log = on_log or (lambda x: None)
    progress = progress_cb or (lambda c, t, m: None)
    output_dir.mkdir(parents=True, exist_ok=True)

    if mode == "inplace":
        results = process_modpack(
            server_root,
            translator,
            output_dir=output_dir,
            pack_format=pack_format,
            on_log=on_log,
            progress_cb=lambda c, t, m: progress(c, t, f"[服务器] {m}"),
            mode="inplace",
        )
        log("服务器文件已直接修改（原 jar 已备份为 .backup）")
        return results

    with tempfile.TemporaryDirectory() as tmp:
        pack_root = Path(tmp) / "ServerChinesePack"
        pack_root.mkdir(parents=True, exist_ok=True)

        results = process_modpack(
            server_root,
            translator,
            output_dir=pack_root,
            pack_format=pack_format,
            on_log=on_log,
            progress_cb=lambda c, t, m: progress(c, t, f"[服务器] {m}"),
        )

        readme = pack_root / "README.txt"
        readme.write_text(
            "服务器汉化安装包\n"
            "================\n\n"
            "本压缩包由 MCModAutoChinese 自动生成。\n\n"
            "使用方法：\n"
            "1. 关闭服务器。\n"
            "2. 将本压缩包里的所有内容解压到服务器根目录（与 mods/、plugins/ 同级）。\n"
            "3. 在 server.properties 中添加（或替换）资源包链接：\n"
            "   resource-pack=你的 AutoChineseResourcePack.zip 下载链接\n"
            "   也可把 AutoChineseResourcePack.zip 放进 resourcepacks/ 文件夹，"
            "让玩家在客户端手动加载。\n"
            "4. 插件汉化补丁（AutoChinesePluginPatch.zip）需要按 jar 手动合并到 plugins/ 下对应插件中；\n"
            "   如需自动修改 plugins 里的 jar，请选择「服务器 → 直接修改 jar」模式。\n"
            "5. 启动服务器。\n\n"
            "注意：操作前请备份服务器！\n",
            encoding="utf-8",
        )

        zip_path = output_dir / "ServerChinesePack.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in pack_root.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(pack_root))
        log(f"服务器汉化安装包已生成：{zip_path}")

    return results


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def summarize(results: List[TargetInfo]) -> Dict[str, int]:
    total = len(results)
    translated = sum(1 for r in results if r.translated_count > 0)
    skipped = sum(1 for r in results if r.skipped)
    errors = sum(1 for r in results if r.error)
    entries = sum(r.translated_count for r in results)
    return {
        "total": total,
        "translated_mods": translated,
        "skipped_mods": skipped,
        "errors": errors,
        "total_entries": entries,
    }
