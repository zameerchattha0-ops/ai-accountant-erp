"""
ERP AI Agent — Centralised Configuration
==========================================
All environment variables are loaded from .env via pydantic-settings.
Secrets (Gemini API key) are retrieved from Supabase Vault at runtime,
never stored in environment or config files.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONSTITUTION_PATH = PROJECT_ROOT / "ERP_AGENT_CONSTITUTION.md"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Supabase --------------------------------------------------------
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_anon_key: str = Field(..., description="Supabase anon/public key")
    supabase_service_role_key: str = Field(
        ..., description="Supabase service-role key (backend only)"
    )

    # ---- Gemini (FALLBACK provider — model config only, key in Vault) ----
    # gemini-2.5-flash was retired by Google for new API users; the API
    # directs new integrations to gemini-3.6-flash.
    gemini_model: str = Field(default="gemini-3.6-flash")
    gemini_temperature: float = Field(default=0.1)
    gemini_max_output_tokens: int = Field(default=8192)
    gemini_top_p: float = Field(default=0.95)
    gemini_top_k: int = Field(default=40)

    # ---- Qwen (PRIMARY runtime AI provider — Alibaba Model Studio) -------
    # Credentials come ONLY from environment/.env — never hardcoded.
    # Endpoint/model are the exact values from the provisioned workspace:
    #   openAiCompatible: https://ws-n3bn056cf66n6765.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
    #   LLM model codes:  qwen3.7-plus, qwen3.6-plus, qwen-max,
    #                     qwen-plus-2025-07-28, qwen-mt-flash, qwen3-vl-*
    qwen_api_key: str = Field(
        default="",
        description="Alibaba Model Studio workspace API key (sk-ws-...)",
    )
    qwen_base_url: str = Field(
        default=(
            "https://ws-n3bn056cf66n6765.ap-southeast-1.maas.aliyuncs.com"
            "/compatible-mode/v1"
        ),
        description="Qwen OpenAI-compatible base URL",
    )
    qwen_dashscope_url: str = Field(
        default=(
            "https://ws-n3bn056cf66n6765.ap-southeast-1.maas.aliyuncs.com"
            "/api/v1"
        ),
        description="Qwen DashScope native base URL (reference only)",
    )
    qwen_model: str = Field(
        default="qwen3.6-plus",
        description="Exact LLM model code from the Model Studio workspace",
    )
    # Verified LIVE via GET /models + capability probes
    # (scripts/verify_qwen_models.py, scripts/probe_qwen_capabilities.py).
    # Ordered fallback chain of ERP-capable Qwen models (text + tool-calling).
    # NOTE: qwen3.7-plus is BANNED from the active chain (constitution rule);
    # qwen-plus-2025-07-28 does NOT exist on the workspace (stale reference).
    qwen_model_chain: str = Field(
        default="qwen3.6-plus,qwen3.5-plus,qwen-max,qwen-plus",
        description="Ordered Qwen fallback chain for text/tool ERP requests",
    )
    qwen_vision_model_chain: str = Field(
        default="qwen3-vl-plus,qwen3-vl-flash",
        description="Ordered Qwen vision-capable chain for document extraction",
    )
    qwen_banned_models: str = Field(
        default="qwen3.7-plus",
        description="Models that must NEVER be selected at runtime",
    )
    qwen_temperature: float = Field(default=0.1)
    qwen_max_output_tokens: int = Field(default=8192)
    qwen_timeout_seconds: float = Field(default=120.0)

    # ---- Provider orchestration ------------------------------------------
    ai_primary_provider: str = Field(
        default="qwen",
        description="PRIMARY runtime AI provider (qwen)",
    )
    ai_fallback_provider: str = Field(
        default="gemini",
        description="FALLBACK runtime AI provider (gemini)",
    )
    provider_health_ttl_seconds: int = Field(
        default=60,
        description="How long a provider health result is cached",
    )

    # ---- Application -----------------------------------------------------
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_log_level: str = Field(default="INFO")

    # ---- Security --------------------------------------------------------
    cors_origins: str = Field(default="http://localhost:3000")
    jwt_secret: str = Field(
        default="change-me",
        description="Legacy HS256 JWT secret (fallback for pre-rotation tokens)",
    )
    jwt_verify_exp: bool = Field(default=True, description="Verify JWT expiration")

    # ---- Database --------------------------------------------------------
    database_pool_size: int = Field(default=10)
    database_max_overflow: int = Field(default=20)

    # ---- Helpers ---------------------------------------------------------
    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def qwen_chain_list(self) -> List[str]:
        """Ordered, de-duplicated text/tool Qwen chain with banned models removed."""
        banned = {m.strip() for m in self.qwen_banned_models.split(",") if m.strip()}
        seen: List[str] = []
        for m in self.qwen_model_chain.split(","):
            m = m.strip()
            if m and m not in banned and m not in seen:
                seen.append(m)
        return seen or [self.qwen_model]

    @property
    def qwen_vision_chain_list(self) -> List[str]:
        """Ordered, de-duplicated vision Qwen chain with banned models removed."""
        banned = {m.strip() for m in self.qwen_banned_models.split(",") if m.strip()}
        seen: List[str] = []
        for m in self.qwen_vision_model_chain.split(","):
            m = m.strip()
            if m and m not in banned and m not in seen:
                seen.append(m)
        return seen

    @property
    def qwen_banned_set(self) -> set:
        return {m.strip() for m in self.qwen_banned_models.split(",") if m.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    return Settings()
