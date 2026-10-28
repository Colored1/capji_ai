"""حفظ الإعدادات والمحادثة في ملف JSON داخل مجلد بيانات التطبيق."""
from __future__ import annotations

import json
import os
from pathlib import Path

from providers import DEFAULT_MODELS

DEFAULT_SYSTEM = (
    "أنت مساعد ذكي ودود ومفيد. أجب بنفس لغة المستخدم، وكن واضحاً ومختصراً "
    "ما لم يُطلب منك التفصيل. استخدم Markdown عند الحاجة."
)


def data_dir() -> Path:
    base = os.environ.get("FLET_APP_STORAGE_DATA") or str(Path.home() / ".ai_chat_app")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _defaults() -> dict:
    return {
        "keys": {"gemini": "", "ollama": "", "anthropic": ""},
        "models": {p: m[0] for p, m in DEFAULT_MODELS.items()},
        "model_lists": {p: list(m) for p, m in DEFAULT_MODELS.items()},
        "selected": "auto",
        "system": DEFAULT_SYSTEM,
        "history": [],
    }


def load() -> dict:
    data = _defaults()
    f = data_dir() / "state.json"
    if f.exists():
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
            for k, v in saved.items():
                if isinstance(v, dict) and isinstance(data.get(k), dict):
                    data[k].update(v)
                else:
                    data[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    return data


def save(state: dict) -> None:
    f = data_dir() / "state.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
