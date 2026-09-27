"""Geografia do dinheiro: quanto vale 1 view em cada país e quando o público está acordado.

rpm_mult: multiplicador de RPM relativo aos EUA (=1.0). Valores de referência de mercado
2025-2026 para conteúdo monetizado; são pontos de partida — o módulo de Análise
recalibra-os com a receita real dos teus canais (YouTube Analytics).
"""
from __future__ import annotations

COUNTRIES: dict[str, dict] = {
    # Tier 1 — onde está o dinheiro
    "US": {"name": "Estados Unidos", "tz": "America/New_York", "lang": "en", "rpm_mult": 1.00, "tier": 1, "pop_weight": 1.00},
    "CA": {"name": "Canadá", "tz": "America/Toronto", "lang": "en", "rpm_mult": 0.82, "tier": 1, "pop_weight": 0.12},
    "AU": {"name": "Austrália", "tz": "Australia/Sydney", "lang": "en", "rpm_mult": 0.88, "tier": 1, "pop_weight": 0.08},
    "GB": {"name": "Reino Unido", "tz": "Europe/London", "lang": "en", "rpm_mult": 0.74, "tier": 1, "pop_weight": 0.20},
    "NZ": {"name": "Nova Zelândia", "tz": "Pacific/Auckland", "lang": "en", "rpm_mult": 0.70, "tier": 1, "pop_weight": 0.02},
    "IE": {"name": "Irlanda", "tz": "Europe/Dublin", "lang": "en", "rpm_mult": 0.62, "tier": 1, "pop_weight": 0.02},
    "CH": {"name": "Suíça", "tz": "Europe/Zurich", "lang": "de", "rpm_mult": 0.90, "tier": 1, "pop_weight": 0.03},
    "NO": {"name": "Noruega", "tz": "Europe/Oslo", "lang": "en", "rpm_mult": 0.80, "tier": 1, "pop_weight": 0.02},
    "DE": {"name": "Alemanha", "tz": "Europe/Berlin", "lang": "de", "rpm_mult": 0.68, "tier": 1, "pop_weight": 0.22},
    "AT": {"name": "Áustria", "tz": "Europe/Vienna", "lang": "de", "rpm_mult": 0.60, "tier": 1, "pop_weight": 0.03},
    "NL": {"name": "Países Baixos", "tz": "Europe/Amsterdam", "lang": "en", "rpm_mult": 0.58, "tier": 1, "pop_weight": 0.05},
    "SE": {"name": "Suécia", "tz": "Europe/Stockholm", "lang": "en", "rpm_mult": 0.60, "tier": 1, "pop_weight": 0.03},
    "DK": {"name": "Dinamarca", "tz": "Europe/Copenhagen", "lang": "en", "rpm_mult": 0.62, "tier": 1, "pop_weight": 0.02},
    "AE": {"name": "Emirados", "tz": "Asia/Dubai", "lang": "en", "rpm_mult": 0.50, "tier": 2, "pop_weight": 0.03},
    "SG": {"name": "Singapura", "tz": "Asia/Singapore", "lang": "en", "rpm_mult": 0.55, "tier": 2, "pop_weight": 0.02},
    # Tier 2
    "FR": {"name": "França", "tz": "Europe/Paris", "lang": "fr", "rpm_mult": 0.48, "tier": 2, "pop_weight": 0.18},
    "BE": {"name": "Bélgica", "tz": "Europe/Brussels", "lang": "fr", "rpm_mult": 0.50, "tier": 2, "pop_weight": 0.03},
    "JP": {"name": "Japão", "tz": "Asia/Tokyo", "lang": "ja", "rpm_mult": 0.50, "tier": 2, "pop_weight": 0.25},
    "KR": {"name": "Coreia do Sul", "tz": "Asia/Seoul", "lang": "ko", "rpm_mult": 0.45, "tier": 2, "pop_weight": 0.10},
    "ES": {"name": "Espanha", "tz": "Europe/Madrid", "lang": "es", "rpm_mult": 0.33, "tier": 2, "pop_weight": 0.12},
    "IT": {"name": "Itália", "tz": "Europe/Rome", "lang": "it", "rpm_mult": 0.33, "tier": 2, "pop_weight": 0.14},
    "PT": {"name": "Portugal", "tz": "Europe/Lisbon", "lang": "pt", "rpm_mult": 0.28, "tier": 2, "pop_weight": 0.03},
    "PL": {"name": "Polónia", "tz": "Europe/Warsaw", "lang": "pl", "rpm_mult": 0.28, "tier": 2, "pop_weight": 0.08},
    "SA": {"name": "Arábia Saudita", "tz": "Asia/Riyadh", "lang": "ar", "rpm_mult": 0.35, "tier": 2, "pop_weight": 0.08},
    # Tier 3 — volume, pouco dinheiro
    "BR": {"name": "Brasil", "tz": "America/Sao_Paulo", "lang": "pt", "rpm_mult": 0.18, "tier": 3, "pop_weight": 0.60},
    "MX": {"name": "México", "tz": "America/Mexico_City", "lang": "es", "rpm_mult": 0.18, "tier": 3, "pop_weight": 0.45},
    "AR": {"name": "Argentina", "tz": "America/Argentina/Buenos_Aires", "lang": "es", "rpm_mult": 0.10, "tier": 3, "pop_weight": 0.15},
    "CO": {"name": "Colômbia", "tz": "America/Bogota", "lang": "es", "rpm_mult": 0.12, "tier": 3, "pop_weight": 0.15},
    "ZA": {"name": "África do Sul", "tz": "Africa/Johannesburg", "lang": "en", "rpm_mult": 0.20, "tier": 3, "pop_weight": 0.08},
    "IN": {"name": "Índia", "tz": "Asia/Kolkata", "lang": "en", "rpm_mult": 0.07, "tier": 3, "pop_weight": 1.60},
    "PH": {"name": "Filipinas", "tz": "Asia/Manila", "lang": "en", "rpm_mult": 0.07, "tier": 3, "pop_weight": 0.30},
    "ID": {"name": "Indonésia", "tz": "Asia/Jakarta", "lang": "id", "rpm_mult": 0.07, "tier": 3, "pop_weight": 0.50},
    "NG": {"name": "Nigéria", "tz": "Africa/Lagos", "lang": "en", "rpm_mult": 0.07, "tier": 3, "pop_weight": 0.20},
    "AO": {"name": "Angola", "tz": "Africa/Luanda", "lang": "pt", "rpm_mult": 0.07, "tier": 3, "pop_weight": 0.04},
    "MZ": {"name": "Moçambique", "tz": "Africa/Maputo", "lang": "pt", "rpm_mult": 0.05, "tier": 3, "pop_weight": 0.03},
}

LANGUAGES: dict[str, dict] = {
    "en": {"name": "Inglês", "geos": ["US", "GB", "CA", "AU", "NZ", "IE", "NL", "SE", "DK", "NO", "AE", "SG", "ZA", "IN", "PH", "NG"]},
    "es": {"name": "Espanhol", "geos": ["MX", "ES", "AR", "CO", "US"]},
    "pt": {"name": "Português", "geos": ["BR", "PT", "AO", "MZ"]},
    "de": {"name": "Alemão", "geos": ["DE", "AT", "CH"]},
    "fr": {"name": "Francês", "geos": ["FR", "BE", "CA", "CH"]},
    "it": {"name": "Italiano", "geos": ["IT", "CH"]},
    "ja": {"name": "Japonês", "geos": ["JP"]},
    "ko": {"name": "Coreano", "geos": ["KR"]},
    "pl": {"name": "Polaco", "geos": ["PL"]},
    "ar": {"name": "Árabe", "geos": ["SA", "AE"]},
    "id": {"name": "Indonésio", "geos": ["ID"]},
}

# Distribuição típica da audiência de um canal EN bem posicionado (sem segmentação).
# Usada para estimar RPM efetivo quando ainda não há dados reais.
DEFAULT_AUDIENCE_MIX: dict[str, dict[str, float]] = {
    "en": {"US": 0.42, "GB": 0.09, "CA": 0.07, "AU": 0.05, "IN": 0.12, "PH": 0.05, "DE": 0.03, "NL": 0.02, "ZA": 0.02, "NG": 0.03, "NZ": 0.01, "IE": 0.01, "SE": 0.01, "SG": 0.01, "AE": 0.01, "NO": 0.01, "DK": 0.01, "BR": 0.03},
    "es": {"MX": 0.35, "ES": 0.18, "AR": 0.12, "CO": 0.12, "US": 0.15, "BR": 0.02, "PT": 0.01, "FR": 0.02, "IT": 0.03},
    "pt": {"BR": 0.78, "PT": 0.12, "AO": 0.04, "MZ": 0.02, "US": 0.03, "ES": 0.01},
    "de": {"DE": 0.72, "AT": 0.12, "CH": 0.12, "NL": 0.02, "US": 0.02},
    "fr": {"FR": 0.66, "BE": 0.08, "CA": 0.14, "CH": 0.05, "US": 0.03, "NG": 0.02, "ZA": 0.02},
}


def effective_rpm_mult(language: str, mix: dict[str, float] | None = None) -> float:
    """RPM médio ponderado pela mistura de países esperada (1.0 = 100% EUA)."""
    mix = mix or DEFAULT_AUDIENCE_MIX.get(language) or {g: 1 for g in LANGUAGES.get(language, {}).get("geos", ["US"])}
    total = sum(mix.values()) or 1.0
    return sum(COUNTRIES.get(g, {"rpm_mult": 0.1})["rpm_mult"] * w for g, w in mix.items()) / total
