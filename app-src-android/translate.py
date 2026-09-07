#!/usr/bin/env python3
"""翻译引擎封装：支持多免费引擎 + LLM API，自动降级切换、重试、术语库、占位符严格保护、繁简中文。"""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class TranslateResult:
    text: str
    engine: str
    cached: bool = False
    confidence: str = "high"  # high / medium / low
    candidates: Dict[str, str] = field(default_factory=dict)
    glossary_hit: bool = False


class BaseEngine(ABC):
    name = "base"

    @abstractmethod
    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        ...


# ---------------------------------------------------------------------------
# 免费引擎（保持原样，仅补充繁体 target 支持）
# ---------------------------------------------------------------------------
class GoogleFreeEngine(BaseEngine):
    name = "google_free"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import GoogleTranslator
            self._translator = GoogleTranslator(source="en", target="zh-CN")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"Google 免费引擎未就绪：{getattr(self, '_error', 'unknown')}")
        from deep_translator import GoogleTranslator
        t = GoogleTranslator(source="en", target=target)
        return t.translate(text)


class BaiduFreeEngine(BaseEngine):
    name = "baidu_free"

    def __init__(self):
        self._ready = False
        try:
            import requests
            self._session = requests.Session()
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"百度免费引擎未就绪：{getattr(self, '_error', 'unknown')}")
        import requests
        to = "zh" if target.startswith("zh") else target
        resp = requests.post(
            "https://fanyi.baidu.com/transapi",
            data={"from": source or "en", "to": to, "query": text, "source": "txt"},
            timeout=15,
        )
        data = resp.json()
        parts = data.get("data", [])
        if parts:
            return "".join(p.get("dst", "") for p in parts)
        raise RuntimeError("百度翻译返回空结果")


class YoudaoFreeEngine(BaseEngine):
    name = "youdao_free"

    def __init__(self):
        self._ready = False
        try:
            import requests
            self._session = requests.Session()
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"有道免费引擎未就绪：{getattr(self, '_error', 'unknown')}")
        import requests
        resp = requests.post(
            "https://fanyi.youdao.com/translate",
            data={"doctype": "json", "type": f"{source or 'en'}2{target.split('-')[-1] if target.startswith('zh') else 'zh'}", "i": text},
            timeout=15,
        )
        data = resp.json()
        result = data.get("translateResult", [])
        if result and isinstance(result, list):
            return "".join(item[0].get("tgt", "") for item in result if item)
        raise RuntimeError("有道翻译返回空结果")


class ArgosEngine(BaseEngine):
    name = "argos"

    def __init__(self):
        self._ready = False
        self._translator = None
        try:
            import argostranslate.package
            import argostranslate.translate
            self._argos = argostranslate
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def _ensure_package(self):
        if self._translator is not None:
            return
        installed = self._argos.package.get_installed_packages()
        pkg = next((p for p in installed if p.from_code == "en" and p.to_code == "zh"), None)
        if pkg is None:
            available = self._argos.package.get_available_packages()
            pkg = next((p for p in available if p.from_code == "en" and p.to_code == "zh"), None)
            if pkg:
                self._argos.package.install_from_path(pkg.download())
                pkg = next(
                    (p for p in self._argos.package.get_installed_packages() if p.from_code == "en" and p.to_code == "zh"),
                    None,
                )
        self._translator = pkg
        if pkg is None:
            raise RuntimeError("Argos 语言包（en->zh）未找到或下载失败")

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"Argos 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        self._ensure_package()
        return self._argos.translate.translate(text, from_code="en", to_code="zh")


class MyMemoryEngine(BaseEngine):
    name = "mymemory"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import MyMemoryTranslator
            self._translator = MyMemoryTranslator(source="en-GB", target="zh-CN")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"MyMemory 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        from deep_translator import MyMemoryTranslator
        t = MyMemoryTranslator(source="en-GB", target=target)
        if len(text) <= 480:
            return t.translate(text)
        parts = re.split(r"(?<=[.!?。！？])\s+", text)
        return " ".join(t.translate(p) for p in parts if p.strip())


class LibreTranslateEngine(BaseEngine):
    name = "libre"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import LibreTranslator
            self._translator = LibreTranslator(source="en", target="zh", base_url="https://libretranslate.de")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"LibreTranslate 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class LingueeEngine(BaseEngine):
    name = "linguee"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import LingueeTranslator
            self._translator = LingueeTranslator(source="english", target="chinese")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"Linguee 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class PonsEngine(BaseEngine):
    name = "pons"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import PonsTranslator
            self._translator = PonsTranslator(source="english", target="chinese")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"PONS 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class BingEngine(BaseEngine):
    name = "bing"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import MicrosoftTranslator
            self._translator = MicrosoftTranslator(source="en", target="zh-Hans")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"Bing 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        from deep_translator import MicrosoftTranslator
        tgt = "zh-Hant" if target.upper().endswith("TW") else "zh-Hans"
        return MicrosoftTranslator(source="en", target=tgt).translate(text)


class PapagoEngine(BaseEngine):
    name = "papago"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import PapagoTranslator
            self._translator = PapagoTranslator(source="en", target="zh-CN")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"Papago 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class YandexEngine(BaseEngine):
    name = "yandex"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import YandexTranslator
            self._translator = YandexTranslator(source="en", target="zh")
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"Yandex 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class DeepLFreeEngine(BaseEngine):
    name = "deepl_free"

    def __init__(self):
        self._ready = False
        try:
            from deep_translator import DeeplTranslator
            self._translator = DeeplTranslator(source="en", target="zh", api_key=None)
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"DeepL 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        return self._translator.translate(text)


class TencentTransmartEngine(BaseEngine):
    """腾讯交互翻译（Transmart）公开接口，无需 Key。"""

    name = "tencent"

    def __init__(self):
        self._ready = False
        try:
            import requests
            self._session = requests.Session()
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"腾讯翻译引擎未就绪：{getattr(self, '_error', 'unknown')}")
        import requests
        resp = requests.post(
            "https://transmart.qq.com/api/imt",
            json={"header": {"fn": "auto_translation", "session": "", "client_key": "browser-edge-chromium-110-Windows_10-zh-CN-true"},
                  "type": "plain", "model_category": "normal", "text_domain": "general",
                  "source": {"lang": "en", "text_list": [text]},
                  "target": {"lang": "zh"}},
            timeout=15,
        )
        data = resp.json()
        lst = data.get("target", {}).get("text_list") or []
        if lst:
            return lst[0]
        raise RuntimeError("腾讯翻译返回空结果")


class CaiyunEngine(BaseEngine):
    """彩云小译公开接口（轻量使用）。"""

    name = "caiyun"

    def __init__(self):
        self._ready = False
        try:
            import requests
            self._session = requests.Session()
            self._ready = True
        except Exception as exc:
            self._error = str(exc)

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"彩云翻译引擎未就绪：{getattr(self, '_error', 'unknown')}")
        import requests
        resp = requests.post(
            "https://api.interpreter.caiyunai.com/v1/translator",
            json={"source": [text], "trans_type": "en2zh", "request_id": "mc-mod", "detect": True},
            timeout=15,
        )
        data = resp.json()
        target_list = data.get("target") or []
        if target_list:
            return target_list[0]
        raise RuntimeError("彩云翻译返回空结果")


class LLMEngine(BaseEngine):
    """OpenAI 兼容接口（OpenAI / DeepSeek / 硅基流动 等）。"""

    name = "llm"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = "gpt-3.5-turbo"):
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

    def translate(self, text: str, source: str = "en", target: str = "zh-CN") -> str:
        if not self._ready:
            raise RuntimeError(f"LLM 引擎未就绪：{getattr(self, '_error', 'unknown')}")
        lang_name = "简体中文" if target.upper().endswith("CN") else "繁体中文"
        prompt = (
            f"You are a professional Minecraft mod translator. "
            f"Translate the following game text from English to {lang_name}. "
            f"Keep placeholders like %s, %d, {0}, <name> unchanged. "
            f"Respond with only the translated text, no explanations.\n\n{text}"
        )
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": "You are a helpful translator."},
                      {"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()


# 多引擎自动切换默认顺序（优先国内可用/无需 Key 引擎）
FREE_ENGINE_ORDER = [
    BaiduFreeEngine,
    YoudaoFreeEngine,
    TencentTransmartEngine,
    CaiyunEngine,
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
    "tencent": TencentTransmartEngine,
    "caiyun": CaiyunEngine,
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
    text: str
    engine: str
    candidates: Dict[str, str]
    confidence: str
    cached: bool = False


# ---------------------------------------------------------------------------
# 统一翻译入口
# ---------------------------------------------------------------------------
class Translator:
    PLACEHOLDER_RE = re.compile(r"(%[\d$]*[sdofxX])|(\{[^{}]*\})|(<[^<>]+>)")
    SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")
    RETRY_DELAYS = [1, 2, 4]

    def __init__(
        self,
        engine: str = "multi_ai",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        delay: float = 0.0,
        fallback: bool = True,
        mode: str = "fast",
        target: str = "zh-CN",
        glossary: Optional[Dict[str, str]] = None,
        on_log: Optional[callable] = None,
    ):
        self.engine_name = engine
        self.delay = delay
        self.fallback = fallback
        self.mode = mode
        self.target = target
        self.glossary = glossary or {}
        self.on_log = on_log or (lambda m: None)
        self._engines: List[BaseEngine] = []
        self._build_engines(engine, api_key, base_url, model)
        self.cache_dir = cache_dir or Path.home() / ".mc_mod_chinese" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache: Dict[str, str] = {}
        self._load_cache()

    def _build_engines(self, engine: str, api_key: Optional[str], base_url: Optional[str], model: Optional[str]):
        engines_to_try: List[BaseEngine] = []
        key = api_key or os.environ.get("OPENAI_API_KEY")

        if engine in ("multi_ai", "multi_free"):
            for cls in FREE_ENGINE_ORDER:
                engines_to_try.append(cls())
            if key:
                engines_to_try.append(LLMEngine(api_key=key, base_url=base_url, model=model or "gpt-3.5-turbo"))
        elif engine == "llm":
            if key:
                engines_to_try.append(LLMEngine(api_key=key, base_url=base_url, model=model or "gpt-3.5-turbo"))
            for cls in FREE_ENGINE_ORDER:
                engines_to_try.append(cls())
        elif engine in FREE_ENGINE_MAP:
            engines_to_try.append(FREE_ENGINE_MAP[engine]())
            for cls in FREE_ENGINE_ORDER:
                if cls is FREE_ENGINE_MAP[engine]:
                    continue
                engines_to_try.append(cls())
            if key:
                engines_to_try.append(LLMEngine(api_key=key, base_url=base_url, model=model or "gpt-3.5-turbo"))
        else:
            for cls in FREE_ENGINE_ORDER:
                engines_to_try.append(cls())

        self._engines = [e for e in engines_to_try if getattr(e, "_ready", False)]

    @property
    def _engine(self) -> BaseEngine:
        return self._engines[0] if self._engines else GoogleFreeEngine()

    def _cache_file(self) -> Path:
        return self.cache_dir / f"cache_{self.engine_name}_{self.target}.json"

    def _load_cache(self):
        cf = self._cache_file()
        if cf.exists():
            try:
                self.cache = json.loads(cf.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}

    def _save_cache(self):
        try:
            self._cache_file().write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _protect_placeholders(text: str) -> Tuple[str, List[str]]:
        tokens = []

        def replace(m):
            tokens.append(m.group(0))
            return f"@@{len(tokens) - 1}@@"

        return Translator.PLACEHOLDER_RE.sub(replace, text), tokens

    @staticmethod
    def _restore_placeholders(text: str, tokens: List[str]) -> str:
        for i, token in enumerate(tokens):
            text = text.replace(f"@@{i}@@", token)
        return text

    def _apply_glossary(self, text: str) -> Tuple[str, bool]:
        """术语库：整句完全匹配优先；否则按词边界替换。返回(处理后文本, 是否命中)。"""
        if not self.glossary:
            return text, False
        stripped = text.strip()
        if stripped in self.glossary:
            return self.glossary[stripped], True
        hit = False
        out = text
        # 按长度降序，避免短词覆盖
        for en in sorted(self.glossary.keys(), key=len, reverse=True):
            if re.search(r"\b" + re.escape(en) + r"\b", out):
                out = re.sub(r"\b" + re.escape(en) + r"\b", self.glossary[en], out)
                hit = True
        return out, hit

    def _call_with_retry(self, engine: BaseEngine, text: str) -> str:
        """带退避重试的单引擎调用。"""
        last_exc = None
        for attempt, wait in enumerate(self.RETRY_DELAYS, 1):
            try:
                return engine.translate(text, "en", self.target)
            except Exception as exc:
                last_exc = exc
                self.on_log(f"  ⚠ {engine.name} 第{attempt}次失败：{self._classify_error(exc)}，{wait}s后重试")
                time.sleep(wait)
        raise RuntimeError(f"{engine.name} 重试耗尽：{self._classify_error(last_exc)}")

    @staticmethod
    def _classify_error(exc) -> str:
        msg = str(exc).lower()
        if any(k in msg for k in ("timeout", "timed out", "read timed")):
            return "网络超时"
        if any(k in msg for k in ("connection", "dns", "resolve", "unreachable", "refused")):
            return "网络连接异常"
        if any(k in msg for k in ("429", "rate", "limit", "quota", "too many")):
            return "接口限流"
        if any(k in msg for k in ("401", "403", "unauthorized", "forbidden", "api key", "invalid")):
            return "鉴权失败"
        if any(k in msg for k in ("empty", "空结果")):
            return "引擎返回空"
        return "引擎故障"

    def _translate_one_with_fallback(self, text: str) -> Tuple[Optional[str], str, Dict[str, str], List[str]]:
        engines = list(self._engines) or [self._engine]
        candidates: Dict[str, str] = {}
        errors: List[str] = []
        best: Optional[str] = None
        best_engine = ""

        for idx, engine in enumerate(engines):
            try:
                res = self._call_with_retry(engine, text)
                candidates[engine.name] = res
                if best is None:
                    best = res
                    best_engine = engine.name
                if self.mode == "fast":
                    break
            except Exception as exc:
                reason = self._classify_error(exc)
                errors.append(f"{engine.name}:{reason}")
                self.on_log(f"  ↳ {engine.name} 失败({reason})，切换下一个引擎")
                if self.fallback and idx < len(engines) - 1:
                    continue
                if not self.fallback:
                    raise
        return best, best_engine, candidates, errors

    def _confidence(self, candidates: Dict[str, str]) -> str:
        if not candidates:
            return "low"
        values = list(candidates.values())
        if len(values) == 1:
            return "medium"
        normalized = [re.sub(r"[\s\W_]", "", v) for v in values]
        if len(set(normalized)) == 1:
            return "high"
        from collections import Counter
        most_common = Counter(normalized).most_common(1)[0][1]
        return "medium" if most_common >= len(values) / 2 else "low"

    def _validate_placeholders(self, original: str, translated: str, tokens: List[str]) -> bool:
        """校验翻译后占位符数量是否一致。"""
        if not tokens:
            return True
        original_count = len(tokens)
        translated_count = sum(translated.count(f"@@{i}@@") for i in range(original_count))
        return translated_count == original_count

    def translate(self, text: str) -> TranslateResult:
        if not text or not text.strip():
            return TranslateResult(text=text, engine=self.engine_name, cached=False)
        if re.fullmatch(r"[\s\d\W]+", text):
            return TranslateResult(text=text, engine=self.engine_name, cached=False)

        # 术语库优先
        gloss_text, gloss_hit = self._apply_glossary(text)
        if gloss_hit:
            # 若整句命中（已完全中文），直接返回
            if gloss_text == text or re.search(r"[\u4e00-\u9fff]", gloss_text) and not re.search(r"[a-zA-Z]{2,}", gloss_text):
                self.on_log(f"  📖 术语库命中：{text[:30]}")
                return TranslateResult(text=gloss_text, engine="glossary", cached=False, confidence="high", glossary_hit=True)

        cache_key = f"{self.engine_name}:{self.mode}:{self.target}:{text}"
        if cache_key in self.cache:
            return TranslateResult(text=self.cache[cache_key], engine=self.engine_name, cached=True)

        protected, tokens = self._protect_placeholders(gloss_text)
        sentences = self.SENTENCE_RE.split(protected) if len(protected) > 80 else [protected]

        translated_parts: List[str] = []
        used_engines: List[str] = []
        all_failed = True
        all_errors: List[str] = []

        for sentence in sentences:
            if not sentence.strip():
                translated_parts.append(sentence)
                continue
            best, best_engine, candidates, errors = self._translate_one_with_fallback(sentence)
            if best is None:
                translated_parts.append(sentence + " [未翻译]")
                used_engines.append("failed")
                all_errors.extend(errors)
                continue
            all_failed = False
            used_engines.append(best_engine)
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

        # 占位符校验：若被破坏则回退原文
        if not self._validate_placeholders(gloss_text, translated, tokens):
            self.on_log(f"  ⚠ 占位符校验失败，回退原文：{text[:30]}")
            restored = text

        if all_failed and len([s for s in sentences if s.strip()]) > 0:
            raise RuntimeError("所有可用翻译引擎均失败：" + "；".join(all_errors))

        engine_label = used_engines[0] if used_engines else self.engine_name
        self.cache[cache_key] = restored
        self._save_cache()
        return TranslateResult(text=restored, engine=engine_label, cached=False, confidence=self._confidence({}) if self.mode == "fast" else "medium")

    def translate_full(self, text: str) -> TranslateDetail:
        if not text or not text.strip():
            return TranslateDetail(text=text, engine=self.engine_name, candidates={}, confidence="high")
        if re.fullmatch(r"[\s\d\W]+", text):
            return TranslateDetail(text=text, engine=self.engine_name, candidates={}, confidence="high")

        gloss_text, _ = self._apply_glossary(text)
        protected, tokens = self._protect_placeholders(gloss_text)
        best, best_engine, candidates, errors = self._translate_one_with_fallback(protected)
        if best is None:
            restored = self._restore_placeholders(protected + " [未翻译]", tokens)
            return TranslateDetail(text=restored, engine="failed", candidates={}, confidence="low")
        restored = self._restore_placeholders(best, tokens)
        if not self._validate_placeholders(gloss_text, best, tokens):
            restored = text
        return TranslateDetail(text=restored, engine=best_engine, candidates=candidates, confidence=self._confidence(candidates))

    def is_ready(self) -> bool:
        return len(self._engines) > 0

    def readiness_message(self) -> str:
        if self.is_ready():
            names = [e.name for e in self._engines]
            mode_str = "快速模式" if self.mode == "fast" else "完整模式（多引擎校验）"
            lang_str = "繁体中文" if self.target.upper().endswith("TW") else "简体中文"
            return f"翻译引擎就绪 [{mode_str}][{lang_str}]（共{len(names)}个，自动切换）：{' -> '.join(names)}"
        return f"翻译引擎 {self.engine_name} 未就绪，请检查依赖或 API 配置"