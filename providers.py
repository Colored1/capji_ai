"""اتصال بمزودي الذكاء الاصطناعي: Gemini وOllama Cloud وClaude (اختياري).

يعتمد على مكتبة بايثون القياسية فقط (urllib) حتى يكون بناء APK أخف وأضمن.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Iterator

TIMEOUT = 90

# عناوين الخدمات (قابلة للتغيير في الاختبارات)
BASE = {
    "gemini": "https://generativelanguage.googleapis.com",
    "ollama": "https://ollama.com",
    "anthropic": "https://api.anthropic.com",
}

PROVIDER_NAMES = {
    "gemini": "Gemini",
    "ollama": "Ollama Cloud",
    "anthropic": "Claude",
}

# نماذج افتراضية؛ يمكن تحديثها من التطبيق نفسه (زر "تحديث القائمة")
DEFAULT_MODELS = {
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "ollama": ["gpt-oss:120b", "deepseek-v3.1:671b", "qwen3-coder:480b", "kimi-k2:1t"],
    "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
}


class ProviderError(Exception):
    """خطأ مفهوم للمستخدم (رسالته بالعربية)."""


def _open(req: urllib.request.Request):
    try:
        return urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        if e.code in (401, 403):
            raise ProviderError("المفتاح غير صالح أو لا يملك صلاحية. راجع الإعدادات.") from e
        if e.code == 404:
            raise ProviderError("النموذج غير موجود. حدّث قائمة النماذج أو غيّر الاسم.") from e
        if e.code == 429:
            raise ProviderError("وصلت إلى حد الاستخدام لهذا المزود. جرّب نموذجاً آخر أو انتظر.") from e
        raise ProviderError(f"خطأ من الخادم ({e.code}): {body}") from e
    except urllib.error.URLError as e:
        raise ProviderError("تعذّر الاتصال. تأكد من الإنترنت.") from e
    except TimeoutError as e:
        raise ProviderError("انتهت مهلة الاتصال.") from e


def _post(url: str, headers: dict, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", **headers}
    return _open(urllib.request.Request(url, data=data, headers=h, method="POST"))


def _get_json(url: str, headers: dict) -> dict:
    with _open(urllib.request.Request(url, headers=headers, method="GET")) as r:
        return json.loads(r.read().decode("utf-8"))


def _lines(resp) -> Iterator[str]:
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if line:
            yield line


def media_kinds(messages: list[dict]) -> set[str]:
    return {md["kind"] for m in messages for md in m.get("media", [])}


# ---------------------------------------------------------------- البث

def _stream_gemini(key: str, model: str, messages: list[dict], system: str) -> Iterator[str]:
    contents = []
    for m in messages:
        parts = [{"text": m["content"] or " "}]
        for md in m.get("media", []):
            parts.append({"inline_data": {"mime_type": md["mime"], "data": md["b64"]}})
        contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts})
    payload: dict = {"contents": contents}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = f"{BASE['gemini']}/v1beta/models/{model}:streamGenerateContent?alt=sse"
    with _post(url, {"x-goog-api-key": key}, payload) as resp:
        for line in _lines(resp):
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            for cand in obj.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text") and not part.get("thought"):
                        yield part["text"]


def _stream_ollama(key: str, model: str, messages: list[dict], system: str) -> Iterator[str]:
    if "pdf" in media_kinds(messages):
        raise ProviderError("Ollama لا يقرأ ملفات PDF هنا. اختر Gemini أو Claude لهذا الملف.")
    msgs = [{"role": "system", "content": system}] if system else []
    for m in messages:
        item = {"role": m["role"], "content": m["content"]}
        imgs = [md["b64"] for md in m.get("media", []) if md["kind"] == "image"]
        if imgs:
            item["images"] = imgs
        msgs.append(item)
    payload = {"model": model, "messages": msgs, "stream": True}
    with _post(f"{BASE['ollama']}/api/chat", {"Authorization": f"Bearer {key}"}, payload) as resp:
        for line in _lines(resp):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise ProviderError(f"خطأ من Ollama: {obj['error']}")
            text = obj.get("message", {}).get("content")
            if text:
                yield text
            if obj.get("done"):
                break


def _stream_anthropic(key: str, model: str, messages: list[dict], system: str) -> Iterator[str]:
    msgs = []
    for m in messages:
        media = m.get("media", [])
        if not media:
            msgs.append({"role": m["role"], "content": m["content"] or " "})
            continue
        blocks = []
        for md in media:
            src = {"type": "base64", "media_type": md["mime"], "data": md["b64"]}
            blocks.append({"type": "document" if md["kind"] == "pdf" else "image", "source": src})
        blocks.append({"type": "text", "text": m["content"] or " "})
        msgs.append({"role": m["role"], "content": blocks})
    payload: dict = {"model": model, "max_tokens": 4096, "messages": msgs, "stream": True}
    if system:
        payload["system"] = system
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    with _post(f"{BASE['anthropic']}/v1/messages", headers, payload) as resp:
        for line in _lines(resp):
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "content_block_delta":
                text = obj.get("delta", {}).get("text")
                if text:
                    yield text
            elif obj.get("type") == "error":
                raise ProviderError(f"خطأ من Claude: {obj.get('error', {}).get('message', '')}")


_STREAMERS: dict[str, Callable[..., Iterator[str]]] = {
    "gemini": _stream_gemini,
    "ollama": _stream_ollama,
    "anthropic": _stream_anthropic,
}


def stream_chat(provider: str, key: str, model: str, messages: list[dict], system: str = "") -> Iterator[str]:
    if not key:
        raise ProviderError(f"لم تُدخل مفتاح {PROVIDER_NAMES[provider]} بعد.")
    got = False
    for chunk in _STREAMERS[provider](key, model, messages, system):
        got = True
        yield chunk
    if not got:
        raise ProviderError("وصل رد فارغ من النموذج.")


# ---------------------------------------------------------------- قوائم النماذج

def fetch_models(provider: str, key: str) -> list[str]:
    if not key:
        raise ProviderError(f"أدخل مفتاح {PROVIDER_NAMES[provider]} أولاً.")
    if provider == "ollama":
        data = _get_json(f"{BASE['ollama']}/api/tags", {"Authorization": f"Bearer {key}"})
        names = [m.get("name") or m.get("model") for m in data.get("models", [])]
    elif provider == "gemini":
        data = _get_json(f"{BASE['gemini']}/v1beta/models?pageSize=200", {"x-goog-api-key": key})
        names = [
            m["name"].split("/", 1)[-1]
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
    else:
        data = _get_json(f"{BASE['anthropic']}/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"})
        names = [m["id"] for m in data.get("data", [])]
    names = [n for n in names if n]
    if not names:
        raise ProviderError("لم تُرجع الخدمة أي نماذج.")
    return sorted(set(names))


# ---------------------------------------------------------------- التوجيه التلقائي

_CODE_WORDS = ("code", "python", "javascript", "bug", "function", "sql", "html", "css", "api",
               "كود", "برمج", "دالة", "خطأ برمجي", "سكربت", "بايثون", "تطبيق")
_DEEP_WORDS = ("حلل", "تحليل", "اشرح بالتفصيل", "قارن", "لخص", "خطة", "analyze", "compare",
               "explain in detail", "summarize", "essay", "مقال")


def classify(text: str) -> str:
    t = text.lower()
    if "```" in t or any(w in t for w in _CODE_WORDS):
        return "code"
    if len(t) > 400 or any(w in t for w in _DEEP_WORDS):
        return "deep"
    return "quick"


_AUTO_ORDER = {
    "code": ["ollama", "anthropic", "gemini"],
    "deep": ["anthropic", "gemini", "ollama"],
    "quick": ["gemini", "ollama", "anthropic"],
}


def auto_plan(text: str, keys: dict, models: dict, kinds: set | None = None) -> list[tuple[str, str]]:
    """ترتيب المحاولات: أنسب مزود أولاً ثم بدائل عند الفشل.

    مع الملفات: PDF يذهب إلى Gemini/Claude فقط، والصور تُفضَّل لها نماذج الرؤية (Gemini ثم Claude).
    """
    kinds = kinds or set()
    if "pdf" in kinds:
        order = ["gemini", "anthropic"]
    elif "image" in kinds:
        order = ["gemini", "anthropic", "ollama"]
    else:
        order = _AUTO_ORDER[classify(text)]
    return [(p, models[p]) for p in order if keys.get(p) and models.get(p)]
