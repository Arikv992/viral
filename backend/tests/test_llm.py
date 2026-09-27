"""Valida o pedido real que o SDK Anthropic envia (via transporte HTTP simulado com SSE) e o parsing da resposta."""
import json

import anthropic
import httpx2

from app import llm as llm_mod
from app.services import finance


def sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events).encode()


def make_stream(text: str, stop: str = "end_turn") -> bytes:
    return sse([
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 1, "cache_read_input_tokens": 3000,
                      "cache_creation_input_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                           "usage": {"output_tokens": 800}}),
        ("message_stop", {"type": "message_stop"}),
    ])


def client_with(handler) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(
        transport=httpx2.MockTransport(handler)), max_retries=0)


def test_request_shape_and_parsing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    from app.config import get_settings

    get_settings.cache_clear()
    llm_mod.reset_llm()
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["beta"] = request.headers.get("anthropic-beta", "")
        return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                               content=make_stream(json.dumps({"x": "ok", "n": 3})))

    L = llm_mod.get_llm()
    L._client = client_with(handler)
    schema = llm_mod.obj({"x": llm_mod.S, "n": llm_mod.INT})
    out = L.json(system="SYS", prompt="hi", schema=schema, effort="low", purpose="t")
    assert out == {"x": "ok", "n": 3}
    b = seen["body"]
    assert b["model"] == "claude-opus-5"
    assert b["thinking"] == {"type": "adaptive"}
    assert b["output_config"]["effort"] == "low"
    assert b["output_config"]["format"]["type"] == "json_schema"
    assert b["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert b["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert b["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in seen["beta"]
    assert b["stream"] is True
    # custo lançado no Cofre
    assert finance.budget_status()["spent"] > 0


def test_refusal_returns_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    from app.config import get_settings

    get_settings.cache_clear()
    llm_mod.reset_llm()
    L = llm_mod.get_llm()
    L._client = client_with(lambda r: httpx2.Response(200, headers={"content-type": "text/event-stream"},
                                                       content=make_stream("", stop="refusal")))
    assert L.json(system="S", prompt="p", schema=llm_mod.obj({"a": llm_mod.S})) is None


def test_fallback_param_rejected_retries_without(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    from app.config import get_settings

    get_settings.cache_clear()
    llm_mod.reset_llm()
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("fallbacks" in body)
        if "fallbacks" in body:
            return httpx2.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "fallbacks: not enabled for this organization"}})
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=make_stream('{"a": "b"}'))

    L = llm_mod.get_llm()
    L._client = client_with(handler)
    assert L.json(system="S", prompt="p", schema=llm_mod.obj({"a": llm_mod.S})) == {"a": "b"}
    assert calls == [True, False]
