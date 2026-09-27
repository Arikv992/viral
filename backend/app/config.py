"""Configuração central. Tudo vem de variáveis de ambiente (ou do ficheiro .env na raiz).

Nenhuma chave é obrigatória: sem chaves a plataforma corre em modo "offline"
(heurísticas locais, imagens procedurais, TTS grátis, publicação em modo exportação).
Cada chave que adicionas desbloqueia uma camada de qualidade/automação.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    # --- Armazenamento ---
    data_dir: Path = ROOT / "data"
    database_url: str = ""  # vazio => sqlite em data_dir/viral.db

    # --- Cérebro (Claude) ---
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5"
    llm_fallbacks: bool = True  # re-executa pedidos recusados noutro modelo (server-side)

    # --- Dados de mercado ---
    youtube_api_key: str = ""  # YouTube Data API v3 (trends, concorrência, comentários)
    google_client_secrets: str = ""  # caminho p/ client_secret.json (OAuth: upload + Analytics)

    # --- Produção ---
    pexels_api_key: str = ""  # stock vídeo/foto grátis
    pixabay_api_key: str = ""  # stock vídeo/foto/música grátis
    fal_api_key: str = ""  # imagens IA (Flux) e vídeo IA (Kling/Veo/etc.)
    elevenlabs_api_key: str = ""  # voz premium
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"  # "Adam" — voz grave, ótima p/ dark

    # --- TikTok (futuro) ---
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""

    # --- Dinheiro ---
    monthly_budget_usd: float = 50.0
    reinvest_ratio: float = 0.5  # % da receita do mês anterior que volta para o orçamento
    usd_to_display: float = 1.0
    currency: str = "USD"

    # --- Piloto automático ---
    autopilot_enabled: bool = False
    autopilot_interval_hours: int = 6
    auto_publish: bool = False  # por omissão pára em "pronto para rever"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'viral.db'}"

    @property
    def media_dir(self) -> Path:
        p = self.data_dir / "media"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def capabilities(self) -> dict[str, bool]:
        return {
            "llm": bool(self.anthropic_api_key),
            "youtube_data": bool(self.youtube_api_key),
            "youtube_oauth": bool(self.google_client_secrets) and Path(self.google_client_secrets).exists(),
            "stock_media": bool(self.pexels_api_key or self.pixabay_api_key),
            "ai_images": bool(self.fal_api_key),
            "ai_video": bool(self.fal_api_key),
            "premium_voice": bool(self.elevenlabs_api_key),
            "tiktok": bool(self.tiktok_client_key and self.tiktok_client_secret),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
