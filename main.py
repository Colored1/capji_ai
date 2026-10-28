"""CAPJI AI — تطبيق دردشة ذكاء اصطناعي لأندرويد (Flet + بايثون).

المزودون: Gemini (Google AI Studio) • Ollama Cloud (DeepSeek, Qwen, gpt-oss, Kimi...) • Claude (اختياري)
الميزات: اختيار النموذج أو «تلقائي» • رفع صور/PDF/ملفات نصية • حركات وانتقالات • شاشة المطوّر
"""
import base64
import inspect
import re
import sys
import threading
import time
import uuid
from pathlib import Path

import flet as ft

import providers as P
import store

# ======================================================================
#  معلومات التطبيق والمطوّر — عدّلها من هنا فقط
# ======================================================================
APP_NAME = "CAPJI AI"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Creative • Media • Technology"
DEV = {
    "name": "أحمد الارحبي",
    "role": "مهندس ومصمم",
    "country": "اليمن 🇾🇪",
    "city": "إب، اليمن",
    "instagram": "axh.d",
    "phone_local": "772678571",
    "phone_intl": "+967772678571",
    "whatsapp": "967772678571",
    "email": "info@capji.com",
}

# ألوان الهوية
GOLD = "#E6CFA8"
BG = "#0D0D0F"
SURFACE = "#1A1A1D"
GRAY = "#8B8B8F"
LOGO_BG = "#FEFEFE"

# المرفقات
IMG_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
TXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".css", ".xml", ".log", ".yaml", ".yml",
           ".sql", ".java", ".kt", ".c", ".cpp", ".ini"}
MAX_MEDIA_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
MAX_PENDING = 5

Btn = getattr(ft, "Button", None) or ft.ElevatedButton

_RENAMES = {"helper_text": "helper", "hint_text": "hint"}


def mk(cls, *args, **kw):
    """ينشئ عنصر Flet ويتكيّف مع اختلاف أسماء الوسائط بين إصدارات Flet."""
    for _ in range(12):
        try:
            return cls(*args, **kw)
        except TypeError as e:
            m = re.search(r"unexpected keyword argument '(\w+)'", str(e))
            if not m:
                raise
            bad = m.group(1)
            val = kw.pop(bad)
            new = _RENAMES.get(bad)
            if new and new not in kw:
                kw[new] = val
    return cls(*args, **kw)


def anim(ms: int = 500):
    """كائن حركة ناعم (يتكيّف مع إصدار Flet)."""
    try:
        return ft.Animation(ms, ft.AnimationCurve.EASE_OUT_CUBIC)
    except Exception:
        try:
            return ft.Animation(ms, "easeOutCubic")
        except Exception:
            return True


def _main(page: ft.Page):
    page.title = APP_NAME
    page.padding = 0
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    try:
        page.theme = mk(ft.Theme, color_scheme_seed=GOLD)
        page.dark_theme = mk(ft.Theme, color_scheme_seed=GOLD)
    except Exception:
        pass
    try:
        page.rtl = True  # واجهة من اليمين لليسار
    except Exception:
        pass
    BACK = ft.Icons.ARROW_FORWARD if getattr(page, "rtl", False) else ft.Icons.ARROW_BACK

    state = store.load()
    ui = {"busy": False, "cancel": False, "col": None}
    blobs: dict = {}       # حمولة الصور/PDF في الذاكرة فقط (id -> dict)
    pending: list = []     # مرفقات الرسالة القادمة

    root = ft.Column(expand=True, spacing=0)
    page.add(ft.SafeArea(expand=True, content=root))

    # ------------------------------------------------------------ أدوات مساعدة
    def tint(opacity=0.07):
        return ft.Colors.with_opacity(opacity, ft.Colors.WHITE)

    def open_url(url: str):
        try:
            r = page.launch_url(url)
            if inspect.isawaitable(r):
                async def go():
                    await r
                page.run_task(go)
        except Exception as ex:
            toast(f"⚠️ تعذّر فتح الرابط: {ex}")

    def toast(msg: str):
        col = ui["col"]
        if col is None:
            return
        banner = mk(ft.Container, content=mk(ft.Text, msg, color=GOLD), bgcolor=SURFACE, padding=10,
                    border_radius=10)
        col.controls.insert(1, banner)
        page.update()

        def _remove():
            try:
                col.controls.remove(banner)
                page.update()
            except Exception:
                pass

        threading.Timer(3.5, _remove).start()

    def selected_label() -> str:
        sel = state["selected"]
        if sel == "auto":
            return "تلقائي"
        prov, _, model = sel.partition("::")
        return f"{P.PROVIDER_NAMES.get(prov, prov)} · {model}"

    def header(title_ctrl, leading=None, actions=()):
        row = []
        if leading:
            row.append(mk(ft.IconButton, icon=leading[0], icon_color=GOLD, on_click=leading[1]))
        row.append(mk(ft.Container, content=title_ctrl, expand=True))
        for icon, cb in actions:
            row.append(mk(ft.IconButton, icon=icon, icon_color=GOLD, on_click=cb))
        return mk(ft.Container, content=mk(ft.Row, controls=row, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                  padding=4, bgcolor=SURFACE)

    def set_view(controls, fade=True):
        """يعرض شاشة جديدة مع تلاشٍ ناعم."""
        col = mk(ft.Column, controls=controls, expand=True, spacing=0)
        wrap = mk(ft.Container, content=col, expand=True, bgcolor=BG,
                  opacity=0 if fade else 1, animate_opacity=anim(380))
        ui["col"] = col
        root.controls = [wrap]
        page.update()
        if fade:
            wrap.opacity = 1
            page.update()

    def show_error(err: str):
        page.bgcolor = BG
        root.controls = [mk(ft.Container, expand=True, bgcolor=BG, padding=16, content=mk(
            ft.Column, scroll=ft.ScrollMode.AUTO, controls=[
                mk(ft.Text, "حدث خطأ — انسخ النص التالي وأرسله للمطوّر", color=GOLD, weight=ft.FontWeight.BOLD),
                mk(ft.Text, err, selectable=True, size=12, color="#ff8a80")]))]
        page.update()

    # ------------------------------------------------------------ الشاشة الافتتاحية
    def show_splash():
        page.bgcolor = LOGO_BG
        logo = mk(ft.Image, src="logo.png", width=260, height=260)
        logo_box = mk(ft.Container, content=logo, opacity=0, scale=0.82,
                      animate_opacity=anim(900), animate_scale=anim(900))
        sub = mk(ft.Container, content=mk(ft.Text, "مساعدك الذكي", size=18, color="#3a3a3d"),
                 opacity=0, offset=ft.Offset(0, 0.4), animate_opacity=anim(900), animate_offset=anim(900))
        bar = mk(ft.ProgressBar, width=140, color=GOLD, bgcolor="#eeeeee")
        bar_box = mk(ft.Container, content=bar, opacity=0, animate_opacity=anim(700))
        splash = mk(ft.Container, expand=True, bgcolor=LOGO_BG, opacity=1, animate_opacity=anim(550),
                    content=mk(ft.Column, controls=[logo_box, sub, bar_box], expand=True, spacing=16,
                               alignment=ft.MainAxisAlignment.CENTER,
                               horizontal_alignment=ft.CrossAxisAlignment.CENTER))
        root.controls = [splash]
        page.update()

        def run():
            try:
                run_inner()
            except Exception:
                import traceback
                tb = traceback.format_exc()
                print(tb)
                show_error(tb)

        def run_inner():
            time.sleep(0.2)
            logo_box.opacity = 1
            logo_box.scale = 1
            page.update()
            time.sleep(0.5)
            sub.opacity = 1
            sub.offset = ft.Offset(0, 0)
            bar_box.opacity = 1
            page.update()
            time.sleep(1.7)
            splash.opacity = 0
            page.update()
            time.sleep(0.6)
            page.bgcolor = BG
            if not any(state["keys"].values()):
                show_settings()
            else:
                show_chat()

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------ الدردشة
    chat_list = ft.ListView(expand=True, spacing=10, padding=12, auto_scroll=True)
    input_box = mk(ft.TextField, hint_text="اكتب رسالتك...", multiline=True, min_lines=1, max_lines=5,
                   expand=True, border_radius=24, filled=True, bgcolor=SURFACE,
                   border_color=ft.Colors.TRANSPARENT, focused_border_color=GOLD)
    send_btn = mk(ft.IconButton, icon=ft.Icons.SEND_ROUNDED, icon_color=BG)
    send_wrap = mk(ft.Container, content=send_btn, bgcolor=GOLD, border_radius=24)
    pending_row = mk(ft.Row, controls=[], wrap=True, spacing=6, run_spacing=6, visible=False)

    def file_icon(kind):
        return {"image": ft.Icons.IMAGE_OUTLINED, "pdf": ft.Icons.PICTURE_AS_PDF_OUTLINED}.get(
            kind, ft.Icons.DESCRIPTION_OUTLINED)

    def short(name: str, n: int = 22) -> str:
        return name if len(name) <= n else name[: n - 1] + "…"

    def bubble(role: str, content: str, label: str = "", files=None, animate=False):
        is_user = role == "user"
        parts = [mk(ft.Text, "أنت" if is_user else (label or APP_NAME), size=11,
                    weight=ft.FontWeight.BOLD, color=BG if is_user else GOLD, opacity=0.75)]
        for f in files or []:
            blob = blobs.get(f.get("id"))
            if f["kind"] == "image" and blob:
                try:
                    parts.append(mk(ft.Image, src_base64=blob["b64"], width=180, border_radius=10))
                    continue
                except Exception:
                    pass
            parts.append(mk(ft.Row, controls=[mk(ft.Icon, file_icon(f["kind"]), size=16, color=BG),
                                              mk(ft.Text, short(f["name"], 30), size=12, color=BG)],
                            tight=True))
        body = (mk(ft.Text, content, selectable=True, color=BG) if is_user
                else mk(ft.Markdown, content or " ", selectable=True))
        parts.append(body)
        box = mk(ft.Container,
                 content=mk(ft.Column, controls=parts, spacing=6, tight=True),
                 bgcolor=GOLD if is_user else SURFACE, padding=12, border_radius=16,
                 opacity=0 if animate else 1, offset=ft.Offset(0, 0.08) if animate else ft.Offset(0, 0),
                 animate_opacity=anim(380), animate_offset=anim(380))
        return box, body

    def pop_in(box):
        box.opacity = 1
        box.offset = ft.Offset(0, 0)
        page.update()

    def suggestion(text):
        def fill(e):
            input_box.value = text
            page.update()

        return mk(ft.Container, content=mk(ft.Text, text, size=13, color=GOLD), on_click=fill,
                  padding=10, border_radius=16, bgcolor=SURFACE)

    def welcome():
        return mk(ft.Container, padding=24, content=mk(
            ft.Column, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12,
            controls=[
                mk(ft.Container, content=mk(ft.Image, src="logo.png", width=110, height=110),
                   bgcolor=LOGO_BG, border_radius=24, padding=6),
                mk(ft.Text, f"أهلاً بك في {APP_NAME}", size=22, weight=ft.FontWeight.BOLD, color=GOLD),
                mk(ft.Text, "اختر النموذج من الأعلى أو اتركه «تلقائي»، ويمكنك إرفاق صور وملفات 📎",
                   color=GRAY, text_align=ft.TextAlign.CENTER),
                suggestion("لخّص لي هذا الملف"),
                suggestion("اقترح فكرة تصميم لشعار"),
                suggestion("ساعدني في كتابة كود بايثون"),
            ]))

    def render_history():
        chat_list.controls.clear()
        if not state["history"]:
            chat_list.controls.append(welcome())
        for m in state["history"]:
            b, _ = bubble(m["role"], m["content"], m.get("label", ""), m.get("files"))
            chat_list.controls.append(b)

    def set_busy(v: bool):
        ui["busy"] = v
        send_btn.icon = ft.Icons.STOP_ROUNDED if v else ft.Icons.SEND_ROUNDED
        page.update()

    # ---- المرفقات
    def render_pending():
        chips = []
        for p in pending:
            def remove(e, pid=p["id"]):
                pending[:] = [x for x in pending if x["id"] != pid]
                render_pending()

            chips.append(mk(ft.Container, bgcolor=SURFACE, border_radius=16, padding=4,
                            content=mk(ft.Row, tight=True, controls=[
                                mk(ft.Icon, file_icon(p["kind"]), size=16, color=GOLD),
                                mk(ft.Text, short(p["name"]), size=12),
                                mk(ft.IconButton, icon=ft.Icons.CLOSE, icon_size=16, on_click=remove)])))
        pending_row.controls = chips
        pending_row.visible = bool(chips)
        page.update()

    def add_attachment(path, name):
        if len(pending) >= MAX_PENDING:
            toast(f"الحد الأقصى {MAX_PENDING} مرفقات للرسالة الواحدة.")
            return
        if not path:
            toast("⚠️ تعذّر قراءة الملف.")
            return
        ext = Path(name).suffix.lower()
        try:
            size = Path(path).stat().st_size
            item = {"id": uuid.uuid4().hex, "name": name}
            if ext in IMG_TYPES or ext == ".pdf":
                if size > MAX_MEDIA_BYTES:
                    toast("⚠️ الملف كبير (الحد 15 ميجابايت).")
                    return
                item.update(kind="image" if ext in IMG_TYPES else "pdf",
                            mime=IMG_TYPES.get(ext, "application/pdf"),
                            b64=base64.b64encode(Path(path).read_bytes()).decode("ascii"))
            elif ext in TXT_EXT:
                txt = Path(path).read_text(encoding="utf-8", errors="replace")
                if len(txt) > MAX_TEXT_CHARS:
                    txt = txt[:MAX_TEXT_CHARS] + "\n...[تم اقتطاع باقي الملف]"
                item.update(kind="text", text=txt)
            else:
                toast("⚠️ نوع الملف غير مدعوم. المدعوم: صور، PDF، ملفات نصية.")
                return
        except Exception as ex:
            toast(f"⚠️ تعذّر قراءة الملف: {ex}")
            return
        pending.append(item)

    def handle_picked(res):
        files = getattr(res, "files", res) or []
        for f in files:
            add_attachment(getattr(f, "path", None), getattr(f, "name", "file"))
        render_pending()

    picker_box = {}

    def get_picker():
        if "p" not in picker_box:
            p = ft.FilePicker()
            if hasattr(page, "services"):
                page.services.append(p)
            else:
                page.overlay.append(p)
            page.update()
            picker_box["p"] = p
            picker_box["async"] = inspect.iscoroutinefunction(getattr(p, "pick_files", None))
        return picker_box["p"], picker_box["async"]

    def on_attach(e=None):
        if ui["busy"]:
            return
        kwargs = {"allow_multiple": True}
        ftype = getattr(ft, "FilePickerFileType", None)
        if ftype is not None:
            kwargs["file_type"] = ftype.CUSTOM
            kwargs["allowed_extensions"] = ["png", "jpg", "jpeg", "webp", "pdf"] + [t.strip(".") for t in TXT_EXT]
        try:
            picker, async_picker = get_picker()
            if async_picker:
                async def go():
                    handle_picked(await picker.pick_files(**kwargs))
                page.run_task(go)
            else:
                picker.on_result = handle_picked
                picker.pick_files(**kwargs)
        except Exception as ex:
            toast(f"⚠️ تعذّر فتح منتقي الملفات: {ex}")

    # ---- بناء الرسائل للمزودين
    def api_messages():
        hist = state["history"][-20:]
        while hist and hist[0]["role"] != "user":
            hist = hist[1:]
        out, budget = [], 3  # نرسل مرفقات الوسائط لآخر 3 رسائل فقط
        for m in reversed(hist):
            content, media = m["content"], []
            for f in m.get("files", []):
                blob = blobs.get(f.get("id"))
                if f["kind"] == "text":
                    content += f"\n\n[الملف: {f['name']}]\n{f['text']}"
                elif blob and budget > 0:
                    media.append(blob)
                else:
                    content += f"\n\n[ملف مرفق سابقاً: {f['name']}]"
            if media:
                budget -= 1
            out.append({"role": m["role"], "content": content, "media": media})
        out.reverse()
        return out

    def plan_for(text: str, kinds: set):
        keys, models = state["keys"], state["models"]
        sel = state["selected"]
        if sel == "auto":
            return P.auto_plan(text, keys, models, kinds)
        prov, _, model = sel.partition("::")
        return [(prov, model)]

    def make_typing():
        dots = [mk(ft.Container, width=8, height=8, border_radius=4, bgcolor=GOLD, opacity=0.25,
                   animate_opacity=anim(350)) for _ in range(3)]
        row = mk(ft.Row, controls=dots, spacing=5)
        stop = threading.Event()

        def loop():
            i = 0
            while not stop.is_set():
                for k, d in enumerate(dots):
                    d.opacity = 1 if k == i % 3 else 0.25
                try:
                    page.update()
                except Exception:
                    pass
                i += 1
                stop.wait(0.35)

        threading.Thread(target=loop, daemon=True).start()
        return row, stop

    def generate(user_text: str):
        msgs = api_messages()
        kinds = P.media_kinds(msgs)
        plan = plan_for(user_text, kinds)
        box, body = bubble("assistant", " ", animate=True)
        chat_list.controls.append(box)
        page.update()
        pop_in(box)

        if not plan:
            body.value = "⚠️ لا يوجد أي مفتاح مُدخل. افتح ⚙️ الإعدادات وأضف مفتاح Gemini أو Ollama."
            state["history"].pop()
            store.save(state)
            set_busy(False)
            return

        typing_row, typing_stop = make_typing()
        col_controls = box.content.controls
        col_controls.insert(1, typing_row)
        page.update()

        def hide_typing():
            if not typing_stop.is_set():
                typing_stop.set()
                try:
                    col_controls.remove(typing_row)
                except ValueError:
                    pass

        text, used, last_err, last_ui = "", "", "", 0.0
        for i, (prov, model) in enumerate(plan):
            used = f"{P.PROVIDER_NAMES[prov]} · {model}"
            text, last_err = "", ""
            try:
                for chunk in P.stream_chat(prov, state["keys"][prov], model, msgs, state["system"]):
                    if ui["cancel"]:
                        break
                    if not text:
                        hide_typing()
                    text += chunk
                    now = time.monotonic()
                    if now - last_ui > 0.06:
                        body.value = text
                        page.update()
                        last_ui = now
                break
            except P.ProviderError as e:
                last_err = str(e)
            except Exception as e:  # أخطاء غير متوقعة
                last_err = f"خطأ غير متوقع: {e}"
            if text:  # وصل جزء من الرد ثم انقطع: لا نبدّل النموذج
                break
            if i + 1 < len(plan):
                body.value = f"⚠️ {used}: {last_err}\n\nجارٍ المحاولة بنموذج آخر..."
                page.update()

        hide_typing()
        if ui["cancel"] and text:
            text += "\n\n_(تم الإيقاف)_"
        if text:
            state["history"].append({"role": "assistant", "content": text, "label": used})
            body.value = text + (f"\n\n⚠️ {last_err}" if last_err else "")
        else:
            state["history"].pop()  # لا نحتفظ بسؤال بلا رد ولا بأخطاء في السياق
            body.value = f"⚠️ {last_err or 'تم الإيقاف.'}"
        store.save(state)
        try:
            box.content.controls[0].value = used
        except Exception:
            pass
        ui["cancel"] = False
        set_busy(False)

    def on_send(e=None):
        if ui["busy"]:
            ui["cancel"] = True
            return
        text = (input_box.value or "").strip()
        if not text and not pending:
            return
        files = []
        for p in pending:
            entry = {"id": p["id"], "name": p["name"], "kind": p["kind"]}
            if p["kind"] == "text":
                entry["text"] = p["text"]
            else:
                blobs[p["id"]] = {"kind": p["kind"], "mime": p["mime"], "b64": p["b64"]}
            files.append(entry)
        if not text:
            text = "اشرح لي محتوى المرفقات."
        pending.clear()
        render_pending()
        input_box.value = ""
        if len(state["history"]) == 0:
            chat_list.controls.clear()
        msg = {"role": "user", "content": text}
        if files:
            msg["files"] = files
        state["history"].append(msg)
        b, _ = bubble("user", text, files=files, animate=True)
        chat_list.controls.append(b)
        set_busy(True)
        pop_in(b)
        threading.Thread(target=generate, args=(text,), daemon=True).start()

    send_btn.on_click = on_send

    def new_chat(e=None):
        if ui["busy"]:
            return
        state["history"] = []
        store.save(state)
        render_history()
        page.update()

    def show_chat(fade=True):
        render_history()
        title = mk(ft.Container, on_click=lambda e: show_picker(), padding=8, content=mk(
            ft.Column, spacing=0, tight=True, controls=[
                mk(ft.Text, APP_NAME, size=15, weight=ft.FontWeight.BOLD, color=GOLD),
                mk(ft.Row, tight=True, spacing=2, controls=[
                    mk(ft.Text, selected_label(), size=11, color=GRAY, overflow=ft.TextOverflow.ELLIPSIS),
                    mk(ft.Icon, ft.Icons.ARROW_DROP_DOWN, size=16, color=GRAY)])]))
        set_view([
            header(title, actions=[(ft.Icons.INFO_OUTLINE, lambda e: show_about()),
                                   (ft.Icons.SETTINGS_OUTLINED, lambda e: show_settings()),
                                   (ft.Icons.ADD_COMMENT_OUTLINED, new_chat)]),
            chat_list,
            mk(ft.Container, padding=8, content=mk(ft.Column, spacing=6, tight=True, controls=[
                pending_row,
                mk(ft.Row, vertical_alignment=ft.CrossAxisAlignment.END, controls=[
                    mk(ft.IconButton, icon=ft.Icons.ATTACH_FILE, icon_color=GOLD, on_click=on_attach),
                    input_box, send_wrap])])),
        ], fade)

    # ------------------------------------------------------------ اختيار النموذج
    def choose(value: str):
        state["selected"] = value
        store.save(state)
        show_chat()

    def show_picker():
        items = [mk(ft.ListTile, leading=mk(ft.Icon, ft.Icons.AUTO_FIX_HIGH, color=GOLD),
                    title=mk(ft.Text, "تلقائي (موصى به)"),
                    subtitle=mk(ft.Text, "يختار الأنسب لسؤالك ويجرّب بديلاً عند الفشل"),
                    selected=state["selected"] == "auto", on_click=lambda e: choose("auto"))]
        any_key = False
        for prov in ("gemini", "ollama", "anthropic"):
            if not state["keys"].get(prov):
                continue
            any_key = True
            items.append(mk(ft.Container, padding=12, content=mk(
                ft.Text, P.PROVIDER_NAMES[prov], weight=ft.FontWeight.BOLD, color=GOLD)))
            for model in state["model_lists"].get(prov, []):
                val = f"{prov}::{model}"
                items.append(mk(ft.ListTile, title=mk(ft.Text, model), selected=state["selected"] == val,
                                on_click=lambda e, v=val: choose(v)))
        if not any_key:
            items.append(mk(ft.Container, padding=16,
                            content=mk(ft.Text, "أضف مفاتيحك من الإعدادات لتظهر النماذج هنا.", color=GRAY)))
        set_view([header(mk(ft.Text, "اختر النموذج", weight=ft.FontWeight.BOLD), leading=(BACK, lambda e: show_chat())),
                  mk(ft.ListView, controls=items, expand=True)])

    # ------------------------------------------------------------ الإعدادات
    def show_settings():
        key_fields, model_fields, sections = {}, {}, []
        hints = {
            "gemini": "من aistudio.google.com/app/api-keys",
            "ollama": "من ollama.com/settings/keys",
            "anthropic": "اختياري، من console.anthropic.com (مدفوع)",
        }
        for prov in ("gemini", "ollama", "anthropic"):
            kf = mk(ft.TextField, label=f"مفتاح {P.PROVIDER_NAMES[prov]}", value=state["keys"].get(prov, ""),
                    password=True, can_reveal_password=True, helper_text=hints[prov], border_radius=12)
            mf = mk(ft.TextField, label="النموذج الافتراضي للوضع التلقائي", value=state["models"].get(prov, ""),
                    border_radius=12, dense=True)
            key_fields[prov], model_fields[prov] = kf, mf

            def refresh(e, prov=prov):
                state["keys"][prov] = key_fields[prov].value.strip()

                def work():
                    try:
                        names = P.fetch_models(prov, state["keys"][prov])
                        state["model_lists"][prov] = names
                        if state["models"].get(prov) not in names:
                            state["models"][prov] = names[0]
                            model_fields[prov].value = names[0]
                        store.save(state)
                        toast(f"تم تحديث نماذج {P.PROVIDER_NAMES[prov]} ({len(names)})")
                    except Exception as ex:
                        toast(f"⚠️ {ex}")
                    page.update()

                threading.Thread(target=work, daemon=True).start()

            sections.append(mk(ft.Container, padding=12, border_radius=14, bgcolor=SURFACE, content=mk(
                ft.Column, spacing=8, controls=[
                    mk(ft.Text, P.PROVIDER_NAMES[prov], weight=ft.FontWeight.BOLD, size=16, color=GOLD),
                    kf, mf, mk(Btn, "تحديث قائمة النماذج", on_click=refresh)])))

        sys_field = mk(ft.TextField, label="تعليمات النظام (شخصية المساعد)", value=state["system"],
                       multiline=True, min_lines=3, max_lines=8, border_radius=12)

        def save(e):
            for prov in key_fields:
                state["keys"][prov] = key_fields[prov].value.strip()
                m = model_fields[prov].value.strip()
                if m:
                    state["models"][prov] = m
                    if m not in state["model_lists"].setdefault(prov, []):
                        state["model_lists"][prov].insert(0, m)
            state["system"] = sys_field.value.strip()
            store.save(state)
            show_chat()

        note = mk(ft.Text, "🔒 المفاتيح تُحفظ على هاتفك فقط ولا تُرسل إلا للمزود نفسه.", size=12, color=GRAY)
        set_view([
            header(mk(ft.Text, "الإعدادات", weight=ft.FontWeight.BOLD), leading=(BACK, lambda e: show_chat())),
            mk(ft.ListView, controls=[*sections, sys_field, note, mk(Btn, "حفظ", on_click=save)],
               expand=True, spacing=12, padding=12),
        ])

    # ------------------------------------------------------------ شاشة المطوّر
    def show_about():
        def tile(icon, title, subtitle, url):
            return mk(ft.Container, opacity=0, offset=ft.Offset(0, 0.25),
                      animate_opacity=anim(450), animate_offset=anim(450),
                      content=mk(ft.ListTile, leading=mk(ft.Icon, icon, color=GOLD),
                                 title=mk(ft.Text, title), subtitle=mk(ft.Text, subtitle, color=GRAY),
                                 on_click=lambda e, u=url: open_url(u)))

        pretty_phone = f"{DEV['phone_local'][:3]} {DEV['phone_local'][3:6]} {DEV['phone_local'][6:]}"
        tiles = [
            tile(ft.Icons.CAMERA_ALT_OUTLINED, "إنستغرام", f"@{DEV['instagram']}",
                 f"https://instagram.com/{DEV['instagram']}"),
            tile(ft.Icons.CHAT_BUBBLE_OUTLINE, "واتساب", pretty_phone, f"https://wa.me/{DEV['whatsapp']}"),
            tile(ft.Icons.PHONE_OUTLINED, "اتصال", pretty_phone, f"tel:{DEV['phone_intl']}"),
            tile(ft.Icons.EMAIL_OUTLINED, "البريد", DEV["email"], f"mailto:{DEV['email']}"),
            tile(ft.Icons.LOCATION_ON_OUTLINED, "الموقع", DEV["city"],
                 "https://maps.google.com/?q=Ibb,Yemen"),
        ]
        card = mk(ft.Container, opacity=0, scale=0.9, animate_opacity=anim(600), animate_scale=anim(600),
                  content=mk(ft.Column, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8, controls=[
                      mk(ft.Container, bgcolor=LOGO_BG, border_radius=28, padding=8,
                         content=mk(ft.Image, src="logo.png", width=150, height=150)),
                      mk(ft.Text, DEV["name"], size=24, weight=ft.FontWeight.BOLD),
                      mk(ft.Text, f"{DEV['role']} • {DEV['country']}", color=GRAY),
                      mk(ft.Container, padding=6, border_radius=14, bgcolor=GOLD,
                         content=mk(ft.Text, "مطوّر التطبيق", size=12, color=BG, weight=ft.FontWeight.BOLD)),
                  ]))
        footer = mk(ft.Container, padding=16, content=mk(
            ft.Text, f"{APP_NAME} • v{APP_VERSION}\n{APP_TAGLINE}", size=12, color=GRAY,
            text_align=ft.TextAlign.CENTER))
        set_view([
            header(mk(ft.Text, "عن المطوّر", weight=ft.FontWeight.BOLD), leading=(BACK, lambda e: show_chat())),
            mk(ft.ListView, controls=[mk(ft.Container, padding=20, content=card), *tiles, footer], expand=True),
        ])

        def reveal():
            time.sleep(0.25)
            card.opacity = 1
            card.scale = 1
            page.update()
            for t in tiles:
                time.sleep(0.1)
                t.opacity = 1
                t.offset = ft.Offset(0, 0)
                page.update()

        threading.Thread(target=reveal, daemon=True).start()

    # ------------------------------------------------------------ البداية
    print("CAPJI: التطبيق بدأ")
    try:
        show_splash()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        show_error(tb)


def main(page: ft.Page):
    """نقطة الدخول: تعرض «جارٍ التحميل» فوراً، وأي خطأ يظهر على الشاشة بدل الشاشة البيضاء."""
    print("CAPJI: main() استُدعيت")
    try:
        page.title = APP_NAME
        page.add(ft.Text("جارٍ التحميل…", size=20))
        page.update()
        print("CAPJI: ظهرت شاشة التحميل")
        try:
            page.clean()
        except Exception:
            page.controls.clear()
        _main(page)
        print("CAPJI: اكتمل بناء الواجهة")
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        try:
            page.controls.clear()
            page.add(ft.Text("حدث خطأ — انسخ النص التالي وأرسله للمطوّر", size=18, color="#c62828"))
            page.add(ft.Text(tb, selectable=True, size=12))
            page.update()
        except Exception:
            pass


if __name__ == "__main__":
    ASSETS = str(Path(__file__).resolve().parent / "assets")
    kwargs = {"assets_dir": ASSETS}
    if "web" in sys.argv:  # py -3.13 main.py web  ← يفتح التطبيق في المتصفح بدل نافذة سطح المكتب
        kwargs["view"] = ft.AppView.WEB_BROWSER
    if hasattr(ft, "run"):
        ft.run(main, **kwargs)
    else:
        ft.app(target=main, **kwargs)
