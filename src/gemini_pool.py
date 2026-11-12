"""
gemini_pool.py
Konfigurasi bersama kandidat model Gemini berbasis discovery `list_models()` API,
rotasi model tahan 404/429/timeout, dan pemanggilan deterministik `temperature=0`.
"""

import os
import threading
import time
import warnings

try:
    from config import load_env_file
    load_env_file()
except Exception:
    pass

# Urutan prioritas fallback jika API list_models tidak dapat dihubungi.
DEFAULT_CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-flash-lite",
]

# Pertahankan alias publik agar skrip lama tetap kompatibel jika mengimpor CANDIDATE_MODELS.
CANDIDATE_MODELS = list(DEFAULT_CANDIDATE_MODELS)

_NON_TEXT_MODEL_TOKENS = (
    "tts",
    "image",
    "nano-banana",
    "lyria",
    "robotics",
    "computer-use",
    "antigravity",
    "deep-research",
    "transcribe",
    "omni",
    "embedding",
    "aqa",
    "imagen",
    "veo",
    "gemma",
)

_MODELS_CACHE_LOCK = threading.Lock()
_DISCOVERED_MODELS_BY_KEY: dict[str, list[str]] = {}


def _is_eligible_text_model(name: str, supported_methods: list[str] | tuple[str, ...] | None = None) -> bool:
    if not name or not isinstance(name, str):
        return False
    short = name.split("/")[-1].strip()
    low = short.lower()
    if not low.startswith("gemini-"):
        return False
    if "pro" not in low and "flash" not in low:
        return False
    if any(tok in low for tok in _NON_TEXT_MODEL_TOKENS):
        return False
    if supported_methods is not None and "generateContent" not in supported_methods:
        return False
    return True


def _rank_model_names(names: list[str]) -> list[str]:
    priority = {m: idx for idx, m in enumerate(DEFAULT_CANDIDATE_MODELS)}

    def _sort_key(n: str):
        low = n.lower()
        if n in priority:
            return (0, priority[n], n)
        if "flash" in low and "preview" not in low:
            return (1, 0, n)
        if "flash" in low:
            return (2, 0, n)
        return (3, 0, n)

    seen = []
    for n in sorted(dict.fromkeys(names), key=_sort_key):
        seen.append(n)
    return seen


def list_available_gemini_models(api_key: str | None = None, force_refresh: bool = False) -> list[str]:
    """
    Mengambil daftar model Gemini text-generation aktif langsung dari Gemini `list_models()` API
    agar tidak menebak nama model secara membabi buta.
    """
    key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
    if not key:
        return list(DEFAULT_CANDIDATE_MODELS)

    with _MODELS_CACHE_LOCK:
        if not force_refresh and key in _DISCOVERED_MODELS_BY_KEY:
            return list(_DISCOVERED_MODELS_BY_KEY[key])

    discovered: list[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import google.generativeai as genai  # type: ignore

        genai.configure(api_key=key, transport="rest")  # type: ignore
        for m in genai.list_models():  # type: ignore
            raw_name = str(getattr(m, "name", "") or "")
            methods = list(getattr(m, "supported_generation_methods", []) or [])
            short_name = raw_name.split("/")[-1].strip()
            if _is_eligible_text_model(short_name, methods):
                discovered.append(short_name)
    except Exception:
        discovered = []

    ranked = _rank_model_names(discovered) if discovered else list(DEFAULT_CANDIDATE_MODELS)
    if discovered:
        with _MODELS_CACHE_LOCK:
            _DISCOVERED_MODELS_BY_KEY[key] = list(ranked)
    return ranked


class GeminiModelPool:
    """Pool model Gemini per modul dengan rotasi 404/429/timeout dan `temperature=0`."""

    def __init__(self, caller_name: str = "gemini"):
        self.caller_name = caller_name
        self._lock = threading.RLock()
        self._models: list[str] = []
        self._idx = 0
        self._exhausted: set[str] = set()
        self._instances: dict[str, object] = {}
        self.quota_exhausted = False
        self.current_model_name = DEFAULT_CANDIDATE_MODELS[0]

    def reset(self) -> None:
        with self._lock:
            self._models = []
            self._idx = 0
            self._exhausted.clear()
            self._instances.clear()
            self.quota_exhausted = False
            self.current_model_name = DEFAULT_CANDIDATE_MODELS[0]

    def _ensure_models_locked(self, api_key: str) -> list[str]:
        if not self._models:
            self._models = list_available_gemini_models(api_key)
            if not self._models:
                self._models = list(DEFAULT_CANDIDATE_MODELS)
            self.current_model_name = self._models[0]
        return self._models

    def get_model(
        self,
        force_next: bool = False,
        mark_exhausted: bool = False,
    ) -> tuple[object | None, str]:
        with self._lock:
            if self.quota_exhausted:
                return None, self.current_model_name

            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key:
                return None, self.current_model_name

            models = self._ensure_models_locked(api_key)

            if mark_exhausted and 0 <= self._idx < len(models):
                self._exhausted.add(models[self._idx])

            if force_next and models:
                self._idx = (self._idx + 1) % len(models)

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", FutureWarning)
                    import google.generativeai as genai  # type: ignore

                genai.configure(api_key=api_key, transport="rest")  # type: ignore

                for _ in range(len(models)):
                    m_name = models[self._idx]
                    if m_name in self._exhausted:
                        self._idx = (self._idx + 1) % len(models)
                        continue
                    try:
                        if m_name not in self._instances:
                            self._instances[m_name] = genai.GenerativeModel(m_name)  # type: ignore
                        self.current_model_name = m_name
                        return self._instances[m_name], m_name
                    except Exception:
                        self._exhausted.add(m_name)
                        self._idx = (self._idx + 1) % len(models)
                        continue

                self.quota_exhausted = True
                return None, self.current_model_name
            except Exception as e:
                print(f"[{self.caller_name}] Gagal inisialisasi Gemini API: {e}", flush=True)
                return None, self.current_model_name

    def peek_active_model_name(self) -> str:
        with self._lock:
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if api_key and not self._models:
                self._ensure_models_locked(api_key)
            return self.current_model_name

    def generate_deterministic(
        self,
        prompt: str,
        timeout: int = 45,
        max_attempts: int = 4,
    ) -> tuple[str | None, str, str]:
        """
        Memanggil Gemini dengan `temperature=0`, backoff eksponensial, dan rotasi model
        saat terjadi 404/429/timeout.
        Returns: (response_text_or_None, model_name_used, error_reason)
        """
        last_error = ""
        last_model = self.peek_active_model_name()

        for attempt in range(max(1, int(max_attempts))):
            model, m_name = self.get_model()
            last_model = m_name
            if model is None:
                last_error = last_error or "seluruh model Gemini gagal diinisialisasi / kuota habis"
                break

            try:
                resp = model.generate_content(  # type: ignore
                    prompt,
                    generation_config={"temperature": 0},
                    request_options={"retry": None, "timeout": timeout},
                )
                return (getattr(resp, "text", None) or "").strip(), m_name, ""
            except Exception as e:
                last_error = str(e)
                err_low = last_error.lower()
                is_not_found = "404" in err_low or "not found" in err_low or "not_found" in err_low
                is_rate_limit = "429" in err_low or "quota" in err_low or "resourceexhausted" in err_low
                is_daily = is_rate_limit and ("perday" in err_low or "daily" in err_low or "generaterequestsperday" in err_low)

                if is_not_found:
                    print(f"[{self.caller_name}] Model '{m_name}' 404/tidak tersedia. Beralih ke model lain...", flush=True)
                    self.get_model(force_next=True, mark_exhausted=True)
                    continue
                if is_daily:
                    print(f"[{self.caller_name}] Kuota harian '{m_name}' habis. Beralih model...", flush=True)
                    self.get_model(force_next=True, mark_exhausted=True)
                    time.sleep(0.5)
                    continue
                if is_rate_limit:
                    backoff = min(8.0, 2.0 * (2 ** attempt))
                    print(f"[{self.caller_name}] Rate limit (429) pada '{m_name}', rotasi model + jeda {backoff:.1f}s...", flush=True)
                    self.get_model(force_next=True, mark_exhausted=False)
                    time.sleep(backoff)
                    continue

                backoff = min(6.0, 1.5 * (2 ** attempt))
                print(f"[{self.caller_name}] Error '{m_name}': {e}. Retry dalam {backoff:.1f}s...", flush=True)
                self.get_model(force_next=True, mark_exhausted=False)
                time.sleep(backoff)

        return None, last_model, last_error
