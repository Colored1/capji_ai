"""اختبار محلي للمزودين بخادم وهمي (بدون إنترنت ولا مفاتيح حقيقية): python test_providers.py"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import providers as P


LAST = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._send(200, json.dumps({"models": [{"name": "b:1"}, {"name": "a:2"}]}))
        if self.path.startswith("/v1beta/models"):
            return self._send(200, json.dumps({"models": [
                {"name": "models/gem-x", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]}))
        if self.path.startswith("/v1/models"):
            return self._send(200, json.dumps({"data": [{"id": "claude-x"}]}))
        self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        LAST[self.path.split("?")[0].split("/")[-1] or "x"] = body
        if self.path.startswith("/v1beta/models/bad"):
            return self._send(429, "{}")
        if self.path.startswith("/v1beta/models/"):
            assert self.headers["x-goog-api-key"] == "K"
            assert len(body["contents"]) == 1 or body["contents"][1]["role"] == "model"
            assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
            ev = "".join("data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": t}]}}]}) + "\n\n"
                         for t in ["مرحبا", " بك"])
            return self._send(200, ev, "text/event-stream")
        if self.path == "/api/chat":
            assert self.headers["Authorization"] == "Bearer K"
            assert body["messages"][0] == {"role": "system", "content": "SYS"}
            ls = [{"message": {"content": "Hel"}}, {"message": {"content": "lo"}}, {"done": True}]
            return self._send(200, "\n".join(json.dumps(x) for x in ls) + "\n", "application/x-ndjson")
        if self.path == "/v1/messages":
            assert self.headers["x-api-key"] == "K" and body["system"] == "SYS"
            ev = "".join("data: " + json.dumps(x) + "\n\n" for x in [
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
                {"type": "message_stop"}])
            return self._send(200, ev, "text/event-stream")
        self._send(404, "{}")


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
for k in P.BASE:
    P.BASE[k] = base

msgs = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}, {"role": "user", "content": "q2"}]
assert "".join(P.stream_chat("gemini", "K", "m", msgs, "SYS")) == "مرحبا بك"
assert "".join(P.stream_chat("ollama", "K", "m", msgs, "SYS")) == "Hello"
assert "".join(P.stream_chat("anthropic", "K", "m", msgs, "SYS")) == "Hi"
assert P.fetch_models("ollama", "K") == ["a:2", "b:1"]
assert P.fetch_models("gemini", "K") == ["gem-x"]
assert P.fetch_models("anthropic", "K") == ["claude-x"]

try:
    list(P.stream_chat("gemini", "K", "bad", msgs, "SYS"))
    raise SystemExit("expected ProviderError")
except P.ProviderError as e:
    assert "حد الاستخدام" in str(e)
try:
    list(P.stream_chat("ollama", "", "m", msgs))
    raise SystemExit("expected ProviderError")
except P.ProviderError as e:
    assert "مفتاح" in str(e)

# ---- المرفقات
img = {"kind": "image", "mime": "image/png", "b64": "QUJD"}
pdf = {"kind": "pdf", "mime": "application/pdf", "b64": "UERG"}
mm = [{"role": "user", "content": "صف الصورة", "media": [img, pdf]}]
list(P.stream_chat("gemini", "K", "m", mm, "SYS"))
parts = LAST["m:streamGenerateContent"]["contents"][0]["parts"]
assert parts[1]["inline_data"] == {"mime_type": "image/png", "data": "QUJD"} and len(parts) == 3
list(P.stream_chat("anthropic", "K", "m", mm, "SYS"))
blocks = LAST["messages"]["messages"][0]["content"]
assert blocks[0]["type"] == "image" and blocks[1]["type"] == "document" and blocks[2]["type"] == "text"
list(P.stream_chat("ollama", "K", "m", [{"role": "user", "content": "x", "media": [img]}], "SYS"))
assert LAST["chat"]["messages"][1]["images"] == ["QUJD"]
try:
    list(P.stream_chat("ollama", "K", "m", mm, "SYS"))
    raise SystemExit("expected pdf error")
except P.ProviderError as e:
    assert "PDF" in str(e)

keys = {"gemini": "k", "ollama": "k", "anthropic": "k"}
assert P.auto_plan("x", keys, {"gemini": "g", "ollama": "o", "anthropic": "c"}, {"pdf"}) == [("gemini", "g"), ("anthropic", "c")]
assert P.auto_plan("x", keys, {"gemini": "g", "ollama": "o", "anthropic": "c"}, {"image"})[0] == ("gemini", "g")
keys = {"gemini": "k", "ollama": "k", "anthropic": ""}
models = {"gemini": "g", "ollama": "o", "anthropic": "c"}
assert P.classify("اكتب لي كود بايثون") == "code"
assert P.classify("مرحبا") == "quick"
assert P.classify("حلل لي هذا الموضوع") == "deep"
assert P.auto_plan("اكتب كود", keys, models) == [("ollama", "o"), ("gemini", "g")]
assert P.auto_plan("مرحبا", keys, models) == [("gemini", "g"), ("ollama", "o")]
print("كل الاختبارات نجحت ✅")
