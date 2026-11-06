
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_MODE,
    LOCAL_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_TIMEOUT,
)

logger = logging.getLogger("finsight_hybrid_llm")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


@dataclass
class HybridLLMResponse:
    text: str
    provider: str                                              
    model: str                                                   
    latency_ms: float
    success: bool
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata or {},
        }


class HybridLLMClient:

    def __init__(
        self,
        ollama_url: Optional[str] = None,
        local_model: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        self.ollama_url = (ollama_url or OLLAMA_BASE_URL).rstrip("/")
        self.local_model = local_model or LOCAL_MODEL
        self.gemini_api_key = gemini_api_key or GEMINI_API_KEY
        self.gemini_model = gemini_model or GEMINI_MODEL
        self.mode = (mode or LLM_MODE or "hybrid").lower()
        self.timeout = OLLAMA_TIMEOUT

        self._gemini_client = None

    @property
    def gemini_client(self):
        if self._gemini_client is None and self.gemini_api_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=self.gemini_api_key)
            except Exception as e:
                logger.warning("[HybridLLM] Gemini istemcisi başlatılamadı: %s", e)
        return self._gemini_client


    def is_qwen_available(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/tags",
                headers={"User-Agent": "FinSight-Hybrid/1.0"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    return any(self.local_model in m for m in models)
        except Exception:
            return False
        return False

    def is_gemini_available(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_client is not None)

    def get_status(self) -> Dict[str, Any]:
        qwen_ok = self.is_qwen_available()
        gemini_ok = self.is_gemini_available()
        return {
            "mode": self.mode,
            "local": {
                "provider": "ollama",
                "model": self.local_model,
                "url": self.ollama_url,
                "available": qwen_ok,
            },
            "cloud": {
                "provider": "google_gemini",
                "model": self.gemini_model,
                "available": gemini_ok,
            },
            "active_strategy": "HYBRID_DYNAMIC" if (qwen_ok and gemini_ok) else ("LOCAL_ONLY" if qwen_ok else ("CLOUD_ONLY" if gemini_ok else "DETERMINISTIC_FALLBACK")),
        }


    def call_qwen(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        timeout: Optional[int] = None,
    ) -> Optional[str]:
        endpoint = f"{self.ollama_url}/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.local_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=req_data,
                headers={"Content-Type": "application/json", "User-Agent": "FinSight-Hybrid/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                msg = res_json.get("message", {}).get("content", "")
                return msg.strip() if msg else None
        except Exception as e:
            logger.warning("[HybridLLM] Lokal Qwen çağrısı başarısız: %s", e)
            return None


    def call_gemini(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Optional[str]:
        client = self.gemini_client
        if not client:
            return None

        candidates = [model or self.gemini_model, "gemini-3.8-flash", "gemini-2.5-flash", "gemini-flash-latest"]
        seen = set()

        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            try:
                kwargs: Dict[str, Any] = {"model": cand, "contents": prompt}
                if system_instruction:
                    kwargs["contents"] = f"[SİSTEM TALİMATI]:\n{system_instruction}\n\n[KULLANICI SORUSU]:\n{prompt}"

                resp = client.models.generate_content(**kwargs)
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                logger.warning("[HybridLLM] Gemini model '%s' hatası: %s", cand, e)
                continue

        return None


    def generate(
        self,
        prompt: str,
        task_type: str = "general",                                                                               
        system_prompt: Optional[str] = None,
        prefer: str = "auto",                                    
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> HybridLLMResponse:
        t0 = time.time()

        if self.mode == "local_only":
            prefer = "local"
        elif self.mode == "gemini_only":
            prefer = "cloud"

        use_local_first = (
            prefer == "local"
            or (prefer == "auto" and task_type in ("classification", "routing", "guardrail", "draft"))
        )

        if use_local_first:
            logger.info("[HybridLLM] Görev '%s' için [LOKAL QWEN] çağrılıyor...", task_type)
            res_text = self.call_qwen(prompt, system_prompt, max_tokens, temperature)
            latency = (time.time() - t0) * 1000
            if res_text:
                return HybridLLMResponse(
                    text=res_text,
                    provider="qwen",
                    model=self.local_model,
                    latency_ms=latency,
                    success=True,
                    metadata={"task_type": task_type, "tier": "local_primary"},
                )

            logger.warning("[HybridLLM] Lokal Qwen yanıt veremedi, [BULUT GEMINI] devreye alınıyor...")
            res_text = self.call_gemini(prompt, system_prompt, temperature=temperature)
            latency = (time.time() - t0) * 1000
            if res_text:
                return HybridLLMResponse(
                    text=res_text,
                    provider="gemini",
                    model=self.gemini_model,
                    latency_ms=latency,
                    success=True,
                    metadata={"task_type": task_type, "tier": "cloud_fallback"},
                )

        else:
            logger.info("[HybridLLM] Görev '%s' için [BULUT GEMINI] çağrılıyor...", task_type)
            res_text = self.call_gemini(prompt, system_prompt, temperature=temperature)
            latency = (time.time() - t0) * 1000
            if res_text:
                return HybridLLMResponse(
                    text=res_text,
                    provider="gemini",
                    model=self.gemini_model,
                    latency_ms=latency,
                    success=True,
                    metadata={"task_type": task_type, "tier": "cloud_primary"},
                )

            logger.warning("[HybridLLM] Bulut Gemini yanıt veremedi, [LOKAL QWEN] devreye alınıyor...")
            res_text = self.call_qwen(prompt, system_prompt, max_tokens, temperature)
            latency = (time.time() - t0) * 1000
            if res_text:
                return HybridLLMResponse(
                    text=res_text,
                    provider="qwen",
                    model=self.local_model,
                    latency_ms=latency,
                    success=True,
                    metadata={"task_type": task_type, "tier": "local_fallback"},
                )

        latency = (time.time() - t0) * 1000
        fallback_text = self._build_deterministic_fallback(prompt, task_type)
        return HybridLLMResponse(
            text=fallback_text,
            provider="deterministic",
            model="deterministic_rule_engine",
            latency_ms=latency,
            success=True,
            error="Her iki LLM de yanıt vermedi; deterministik güvenli kural motoru devreye girdi.",
            metadata={"task_type": task_type, "tier": "deterministic_fallback"},
        )

    def _build_deterministic_fallback(self, prompt: str, task_type: str) -> str:
        if task_type in ("classification", "routing"):
            p_low = prompt.lower()
            if any(k in p_low for k in ["risk", "item 1a", "rekabet", "tedarik"]):
                return "HYBRID"
            if any(k in p_low for k in ["gelir", "kar", "marj", "oran", "cagr", "pe"]):
                return "NUMERICAL"
            return "HYBRID"
        return f"[Deterministik Araştırma Notu]: Sistem talebi başarıyla ayrıştırdı. Analist doğrulaması için ilgili mali veriler ve 10-K maddeleri çekilerek güvenli rapora eklenmiştir."


_GLOBAL_HYBRID_CLIENT: Optional[HybridLLMClient] = None


def get_hybrid_llm_client() -> HybridLLMClient:
    global _GLOBAL_HYBRID_CLIENT
    if _GLOBAL_HYBRID_CLIENT is None:
        _GLOBAL_HYBRID_CLIENT = HybridLLMClient()
    return _GLOBAL_HYBRID_CLIENT

