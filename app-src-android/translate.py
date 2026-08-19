#!/usr/bin/env python3
"""翻译引擎封装：支持多免费引擎 + LLM API，自动降级切换。"""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class TranslateResult:
    text: str
    engine: str
    cached: bool = False


class BaseEngine(ABC):
    name = "base"

    @abstractmethod
    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        ...


class GoogleFreeEngine(BaseEngine):
    """Google 免费翻译（需要能访问 Google，优先级最低）。"""

    name = "google_free"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import GoogleTranslator

            self._translator = GoogleTranslator(source="en", target="zh-CN")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"Google 免费引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        return self._translator.translate(text)


class BaiduFreeEngine(BaseEngine):
    """百度翻译免费版（需要联网，无需 API Key 使用公共接口）。"""

    name = "baidu_free"

    def __init__(self):
        self._ready = False
        try:
            import requests

            self._session = requests.Session()
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"百度免费引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        try:
            # 百度翻译公开 API（非商业，轻量使用）
            url = "https://fanyi.baidu.com/transapi"
            resp = self._session.post(
                url,
                data={"from": source or "en", "to": target or "zh", "query": text, "source": "txt"},
                timeout=15,
            )
            data = resp.json()
            parts = data.get("data", [])
            if parts:
                return "".join(p.get("dst", "") for p in parts)
            raise RuntimeError("百度翻译返回空结果")
        except Exception as exc:
            raise RuntimeError(f"百度翻译失败：{exc}")


class YoudaoFreeEngine(BaseEngine):
    """有道翻译公开接口（无需 Key，轻量使用）。"""

    name = "youdao_free"

    def __init__(self):
        self._ready = False
        try:
            import requests

            self._session = requests.Session()
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"有道免费引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        try:
            url = "https://fanyi.youdao.com/translate"
            resp = self._session.post(
                url,
                data={
                    "doctype": "json",
                    "type": f"{source or 'en'}2{target or 'zh'}",
                    "i": text,
                },
                timeout=15,
            )
            data = resp.json()
            result = data.get("translateResult", [])
            if result and isinstance(result, list):
                return "".join(item[0].get("tgt", "") for item in result if item)
            raise RuntimeError("有道翻译返回空结果")
        except Exception as exc:
            raise RuntimeError(f"有道翻译失败：{exc}")


class ArgosEngine(BaseEngine):
    """Argos Translate 本地/离线翻译引擎，无需联网即可使用。"""

    name = "argos"

    def __init__(self):
        self._ready = False
        try:
            import argostranslate.package
            import argostranslate.translate

            self._translate = argostranslate.translate.translate
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"Argos 引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        try:
            return self._translate(text, from_code=source or "en", to_code=target or "zh")
        except Exception as exc:
            raise RuntimeError(f"Argos 翻译失败：{exc}")


class MyMemoryEngine(BaseEngine):
    """MyMemory 免费翻译，无需 Key，国内通常可访问。"""

    name = "mymemory"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import MyMemoryTranslator

            self._translator = MyMemoryTranslator(source="en-GB", target="zh-CN")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"MyMemory 引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        # MyMemory 单句有长度限制，超过就按句切分
        if len(text) <= 480:
            return self._translator.translate(text)
        parts = re.split(r"(?<=[.!?。！？])\s+", text)
        out_parts = []
        for p in parts:
            if p.strip():
                out_parts.append(self._translator.translate(p))
        return " ".join(out_parts)


class LibreTranslateEngine(BaseEngine):
    """LibreTranslate 免费开源翻译，使用公共实例。"""

    name = "libre"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import LibreTranslator

            # 使用官方公共实例
            self._translator = LibreTranslator(
                source="en", target="zh",
                base_url="https://libretranslate.de",
            )
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"LibreTranslate 引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        return self._translator.translate(text)


class LingueeEngine(BaseEngine):
    """Linguee 翻译（词典风格，适合短词）。"""

    name = "linguee"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import LingueeTranslator

            self._translator = LingueeTranslator(source="english", target="chinese")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"Linguee 引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        return self._translator.translate(text)


class PonsEngine(BaseEngine):
    """PONS 翻译。"""

    name = "pons"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import PonsTranslator

            self._translator = PonsTranslator(source="english", target="chinese")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(
                f"PONS 引擎未就绪：{getattr(self, '_error', 'unknown')}"
            )
        return self._translator.translate(text)


class BingEngine(BaseEngine):
    """Microsoft Bing 免费翻译（通过 deep-translator）。"""

    name = "bing"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import MicrosoftTranslator

            self._translator = MicrosoftTranslator(source="en", target="zh-Hans")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(f"Bing 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class PapagoEngine(BaseEngine):
    """Naver Papago 免费翻译（通过 deep-translator，短文本效果好）。"""

    name = "papago"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import PapagoTranslator

            self._translator = PapagoTranslator(source="en", target="zh-CN")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(f"Papago 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class YandexEngine(BaseEngine):
    """Yandex 免费翻译（通过 deep-translator）。"""

    name = "yandex"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import YandexTranslator

            self._translator = YandexTranslator(source="en", target="zh")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(f"Yandex 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class DeepLFreeEngine(BaseEngine):
    """DeepL 免费翻译（通过 deep-translator，无需 Key 时使用公共接口）。"""

    name = "deepl_free"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import DeeplTranslator

            self._translator = DeeplTranslator(source="en", target="zh", api_key=None)
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(f"DeepL 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class LLMEngine(BaseEngine):
    """OpenAI 兼容接口（OpenAI / DeepSeek / 硅基流动 等）。"""

    name = "llm"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-3.5-turbo",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client = None
        self._ready = False
        if api_key:
            try:
                import openai

                self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
                self._ready = True
            except Exception as exc:
                self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh") -> str:
        if not self._ready:
            raise RuntimeError(f"LLM 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        prompt = (
            "You are a professional Minecraft mod translator. "
            "Translate the following game text from English to Simplified Chinese. "
            "Keep placeholders like %s, %d, {0}, <name> unchanged. "
            "Respond with only the translated text, no explanations.\n\n"
            f"{text}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful translator."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            raise RuntimeError(f"LLM 翻译失败：{exc}")


# 多引擎自动切换时的默认尝试顺序（Google 放最后，优先国内可用/无需 Key 引擎）
FREE_ENGINE_ORDER = [
    BaiduFreeEngine,
    YoudaoFreeEngine,
    BingEngine,
    PapagoEngine,
    MyMemoryEngine,
    LibreTranslateEngine,
    DeepLFreeEngine,
    ArgosEngine,
    GoogleFreeEngine,
    LingueeEngine,
    PonsEngine,
    YandexEngine,
]

FREE_ENGINE_MAP = {
    "baidu_free": BaiduFreeEngine,
    "youdao_free": YoudaoFreeEngine,
    "bing": BingEngine,
    "papago": PapagoEngine,
    "mymemory": MyMemoryEngine,
    "libre": LibreTranslateEngine,
    "deepl_free": DeepLFreeEngine,
    "linguee": LingueeEngine,
    "pons": PonsEngine,
    "google_free": GoogleFreeEngine,
    "argos": ArgosEngine,
    "yandex": YandexEngine,
}


@dataclass
class TranslateDetail:
    """完整版返回的详细翻译结果，包含多个引擎结果和置信度。"""

    text: str
    engine: str
    candidates: Dict[str, str]
    confidence: str  # high / medium / low
    cached: bool = False


class Translator:
    """统一翻译入口：缓存 + 占位符保护 + 多引擎自动降级 + 快速/完整模式。"""

    PLACEHOLDER_RE = re.compile(r"(%[\d$]*[sdofxX])|(\{[^{}]*\})|(<[^<>]+>)")
    # 用于把长文本拆成句子，逐句翻译/降级
    SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")

    def __init__(
        self,
        engine: str = "multi_free",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        delay: float = 0.0,
        fallback: bool = True,
        mode: str = "fast",  # fast / full
    ):
        self.engine_name = engine
        self.delay = delay
        self.fallback = fallback
        self.mode = mode
        self._engines: List[BaseEngine] = []
        self._build_engines(engine, api_key, base_url, model)
        self.cache_dir = cache_dir or Path.home() / ".mc_mod_chinese" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache: Dict[str, str] = {}
        self._load_cache()

    def _build_engines(
        self,
        engine: str,
        api_key: Optional[str],
        base_url: Optional[str],
        model: Optional[str],
    ):
        engines_to_try: List[BaseEngine] = []
        key = api_key or os.environ.get("OPENAI_API_KEY")

        if engine == "llm":
            # 首选 LLM，失败降级到多免费引擎
            if key:
                engines_to_try.append(
                    LLMEngine(api_key=key, base_url=base_url, model=model or "gpt-3.5-turbo")
                )
            for cls in FREE_ENGINE_ORDER:
                engines_to_try.append(cls())

        elif engine == "multi_free":
            # 多引擎自动切换：依次尝试所有免费引擎
            for cls in FREE_ENGINE_ORDER:
                engines_to_try.append(cls())
            # 有 API Key 就把 LLM 放到最后兜底
            if key:
                engines_to_try.append(
                    LLMEngine(api_key=key, base_url=base_url, model=model or "gpt-3.5-turbo")
                )

        elif engine in FREE_ENGINE_MAP:
            # 用户指定某一个免费引擎，但仍然把其它免费引擎当兜底
            engines_to_try.append(FREE_ENGINE_MAP[engine]())
            for cls in FREE_ENGINE_ORDER:
                if cls is FREE_ENGINE_MAP[engine]:
                    continue
                engines_to_try.append(cls())
            if key:
                engines_to_try.append(
                    LLMEngine(api_key=key, base_url=base_url, model=model or "gpt-3.5-turbo")
                )
        else:
            # 未知，退化成多免费引擎
            for cls in FREE_ENGINE_ORDER:
                engines_to_try.append(cls())

        self._engines = [e for e in engines_to_try if getattr(e, "_ready", False)]

    @property
    def _engine(self) -> BaseEngine:
        if self._engines:
            return self._engines[0]
        return GoogleFreeEngine()

    def _cache_file(self) -> Path:
        return self.cache_dir / f"cache_{self.engine_name}.json"

    def _load_cache(self):
        cf = self._cache_file()
        if cf.exists():
            try:
                self.cache = json.loads(cf.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}

    def _save_cache(self):
        try:
            self._cache_file().write_text(
                json.dumps(self.cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def _protect_placeholders(text: str) -> tuple:
        tokens = []

        def replace(m):
            tokens.append(m.group(0))
            return f"@@{len(tokens) - 1}@@"

        protected = Translator.PLACEHOLDER_RE.sub(replace, text)
        return protected, tokens

    @staticmethod
    def _restore_placeholders(text: str, tokens: List[str]) -> str:
        for i, token in enumerate(tokens):
            text = text.replace(f"@@{i}@@", token)
        return text

    def _translate_one_with_fallback(
        self, text: str
    ) -> Tuple[Optional[str], str, Dict[str, str], List[str]]:
        """
        对单句文本尝试所有可用引擎，返回：
        (最佳翻译, 最佳引擎名, {引擎名: 结果}, 错误列表)
        如果全部失败，最佳翻译为 None。
        """
        engines = list(self._engines)
        if not engines:
            engines = [self._engine]

        candidates: Dict[str, str] = {}
        errors: List[str] = []
        best: Optional[str] = None
        best_engine = ""

        for engine in engines:
            try:
                res = engine.translate(text, "en", "zh")
                candidates[engine.name] = res
                if best is None:
                    best = res
                    best_engine = engine.name
                # 快速模式：只要有一个成功就返回
                if self.mode == "fast":
                    break
            except Exception as exc:
                errors.append(f"{engine.name}:{exc}")
                if self.fallback and len(engines) > 1:
                    continue
                # 非 fallback 模式直接抛错
                raise

        return best, best_engine, candidates, errors

    def _confidence(self, candidates: Dict[str, str]) -> str:
        """根据多引擎结果一致性判断置信度。"""
        if not candidates:
            return "low"
        values = list(candidates.values())
        if len(values) == 1:
            return "medium"
        # 简单相似度：去掉空格、标点和下划线后对比
        normalized = [re.sub(r"[\s\W_]", "", v) for v in values]
        if len(set(normalized)) == 1:
            return "high"
        # 超过一半相同视为 medium
        from collections import Counter

        most_common = Counter(normalized).most_common(1)[0][1]
        if most_common >= len(values) / 2:
            return "medium"
        return "low"

    def translate(self, text: str) -> TranslateResult:
        """对外统一接口：快速模式直接返回；完整模式做逐句交叉验证。"""
        if not text or not text.strip():
            return TranslateResult(text=text, engine=self.engine_name, cached=False)
        if re.fullmatch(r"[\s\d\W]+", text):
            return TranslateResult(text=text, engine=self.engine_name, cached=False)

        cache_key = f"{self.engine_name}:{self.mode}:{text}"
        if cache_key in self.cache:
            return TranslateResult(
                text=self.cache[cache_key], engine=self.engine_name, cached=True
            )

        protected, tokens = self._protect_placeholders(text)

        # 短文本或不含句子分隔符，直接作为一句处理
        sentences = self.SENTENCE_RE.split(protected) if len(protected) > 80 else [protected]

        translated_parts: List[str] = []
        used_engines: List[str] = []
        all_failed = True

        for sentence in sentences:
            if not sentence.strip():
                translated_parts.append(sentence)
                continue

            best, best_engine, candidates, errors = self._translate_one_with_fallback(
                sentence
            )

            if best is None:
                # 全部失败：保留原文并标注
                translated_parts.append(sentence + " [未翻译]")
                used_engines.append("failed")
                continue

            all_failed = False
            used_engines.append(best_engine)

            # 完整模式：置信度低时追加标记
            if self.mode == "full":
                conf = self._confidence(candidates)
                if conf == "low":
                    best = best + " [需人工核对]"
                elif conf == "medium":
                    best = best + " [已多引擎校验]"

            translated_parts.append(best)

            if self.delay > 0:
                time.sleep(self.delay)

        translated = "".join(translated_parts)
        restored = self._restore_placeholders(translated, tokens)

        # 如果整段全部失败，抛出异常让上层知道
        if all_failed and len([s for s in sentences if s.strip()]) > 0:
            raise RuntimeError("所有可用翻译引擎均失败：" + "；".join(errors))

        engine_label = used_engines[0] if used_engines else self.engine_name
        self.cache[cache_key] = restored
        self._save_cache()
        return TranslateResult(text=restored, engine=engine_label, cached=False)

    def translate_full(self, text: str) -> TranslateDetail:
        """完整版接口：返回详细结果，含候选和置信度。"""
        if not text or not text.strip():
            return TranslateDetail(
                text=text, engine=self.engine_name, candidates={}, confidence="high"
            )
        if re.fullmatch(r"[\s\d\W]+", text):
            return TranslateDetail(
                text=text, engine=self.engine_name, candidates={}, confidence="high"
            )

        protected, tokens = self._protect_placeholders(text)
        best, best_engine, candidates, errors = self._translate_one_with_fallback(protected)

        if best is None:
            restored = self._restore_placeholders(protected + " [未翻译]", tokens)
            return TranslateDetail(
                text=restored,
                engine="failed",
                candidates={},
                confidence="low",
            )

        restored = self._restore_placeholders(best, tokens)
        conf = self._confidence(candidates)
        return TranslateDetail(
            text=restored,
            engine=best_engine,
            candidates=candidates,
            confidence=conf,
        )

    def is_ready(self) -> bool:
        return len(self._engines) > 0

    def readiness_message(self) -> str:
        if self.is_ready():
            names = [e.name for e in self._engines]
            mode_str = "快速模式" if self.mode == "fast" else "完整模式（多引擎校验）"
            return f"翻译引擎就绪 [{mode_str}]（共{len(names)}个，自动切换）：{' -> '.join(names)}"
        return f"翻译引擎 {self.engine_name} 未就绪，请检查依赖或 API 配置"
