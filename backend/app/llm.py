"""Cérebro da plataforma: Claude com saída JSON estruturada.

- Cada chamada devolve JSON validado contra um schema (output_config.format).
- O custo de cada chamada é lançado no Ledger automaticamente (nada escapa ao Cofre).
- Sem ANTHROPIC_API_KEY, `json()` devolve None e cada serviço usa o seu fallback heurístico.
- O esforço (effort) é escolhido por tarefa: 'low' p/ classificação em massa,
  'high' p/ guiões e estratégia — é aqui que se corta custo sem cortar qualidade.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from .config import get_settings
from .knowledge.providers import llm_cost

log = logging.getLogger("viral.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


# ---------- helpers de schema (structured outputs exige additionalProperties=false) ----------
def obj(props: dict[str, Any], required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


S = {"type": "string"}
NUM = {"type": "number"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


class LLM:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: anthropic.Anthropic | None = None
        self._fallbacks_ok = self.settings.llm_fallbacks

    @property
    def available(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key, max_retries=3)
        return self._client

    def json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict,
        effort: str = "medium",
        max_tokens: int = 16000,
        purpose: str = "",
        channel_id: int | None = None,
        video_id: int | None = None,
    ) -> dict | None:
        if not self.available:
            return None
        params: dict[str, Any] = dict(
            model=self.settings.llm_model,
            max_tokens=max_tokens,
            # System estável e com cache: os prompts-mestre são longos e repetem-se em cada chamada.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            msg = self._call(params)
        except anthropic.BadRequestError as e:
            if self._fallbacks_ok and "fallback" in str(e).lower():
                self._fallbacks_ok = False  # conta/plataforma sem fallbacks: desliga e repete
                msg = self._call(params)
            else:
                log.error("LLM 400 (%s): %s", purpose, e)
                return None
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            log.error("LLM falhou (%s): %s", purpose, e)
            return None

        self._book_cost(msg, purpose, channel_id, video_id)
        if msg.stop_reason == "refusal":
            log.warning("LLM recusou (%s): %s", purpose, getattr(msg, "stop_details", None))
            return None
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.error("LLM devolveu JSON inválido (%s, stop=%s)", purpose, msg.stop_reason)
            return None

    def _call(self, params: dict):
        # Streaming evita timeouts em guiões longos (docs de 1-3h para dormir).
        if self._fallbacks_ok:
            with self.client.beta.messages.stream(
                **params, betas=[FALLBACK_BETA], fallbacks="default"
            ) as stream:
                return stream.get_final_message()
        with self.client.messages.stream(**params) as stream:
            return stream.get_final_message()

    def _book_cost(self, msg, purpose: str, channel_id: int | None, video_id: int | None) -> None:
        u = msg.usage
        tokens_in = (u.input_tokens or 0) + int((getattr(u, "cache_creation_input_tokens", 0) or 0) * 1.25)
        tokens_in += int((getattr(u, "cache_read_input_tokens", 0) or 0) * 0.1)
        cost = llm_cost(getattr(msg, "model", self.settings.llm_model), tokens_in, u.output_tokens or 0)
        from .services.finance import book_cost

        book_cost("llm", cost, memo=f"{purpose} ({u.input_tokens}in/{u.output_tokens}out)",
                  channel_id=channel_id, video_id=video_id)


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm


def reset_llm() -> None:
    global _llm
    _llm = None
