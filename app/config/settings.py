"""
Enterprise configuration management with comprehensive security settings.
Supports multiple environments with proper secret handling.
"""
import os
import json
from typing import Optional, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """Database configuration for SQLite and MongoDB."""
    sqlite_url: str = Field(default="sqlite:///./data/governance_agent.db")
    mongo_url: str = Field(default="mongodb://localhost:27017")
    mongo_database: str = Field(default="governance_agent")
    
    model_config = {"env_prefix": "DB_"}


class LLMSettings(BaseSettings):
    """LLM provider configuration with fallback support."""
    openai_api_key: Optional[str] = Field(default=None)
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    model_name: str = Field(default="gpt-4-turbo-preview")
    max_tokens: int = Field(default=4000)
    temperature: float = Field(default=0.1)
    timeout_seconds: int = Field(default=30)
    use_mock_llm: bool = Field(default=False)  # For testing without API key
    
    model_config = {"env_prefix": "LLM_"}


class GuardrailsSettings(BaseSettings):
    """NeMo Guardrails configuration."""
    config_path: str = Field(default="./app/guardrails/config.yml")
    rails_path: str = Field(default="./app/guardrails/rails")
    enable_by_default: bool = Field(default=True)
    block_on_violation: bool = Field(default=True)
    log_violations: bool = Field(default=True)
    
    model_config = {"env_prefix": "GUARDRAILS_"}


class SecuritySettings(BaseSettings):
    """Security and RBAC configuration."""
    secret_key: str = Field(default="dev-secret-key-change-in-production")
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30)
    
    # PII Detection patterns
    pii_patterns: List[str] = Field(default_factory=lambda: [
        r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # Phone
        r'\b4[0-9]{12}(?:[0-9]{3})?\b',  # Credit card (Visa)
    ])
    
    # Role-based permissions
    employee_allowed_tools: List[str] = Field(default_factory=lambda: [
        "search_internal_kb",
        "create_ticket",
        "web_search"
    ])
    
    admin_allowed_tools: List[str] = Field(default_factory=lambda: [
        "search_internal_kb",
        "create_ticket", 
        "get_user_profile",
        "web_search",
        "query_database",
        "access_sensitive_docs"
    ])
    
    @field_validator('employee_allowed_tools', mode='before')
    @classmethod
    def parse_employee_tools(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v
    
    @field_validator('admin_allowed_tools', mode='before')
    @classmethod
    def parse_admin_tools(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v
    
    model_config = {"env_prefix": "SECURITY_"}


class ObservabilitySettings(BaseSettings):
    """Logging and tracing configuration."""
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")
    enable_tracing: bool = Field(default=True)
    trace_sampling_rate: float = Field(default=1.0)
    
    model_config = {"env_prefix": "OBS_"}


class APISettings(BaseSettings):
    """FastAPI and rate limiting configuration."""
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    reload: bool = Field(default=True)
    
    # Rate limiting
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_per_minute: int = Field(default=60)
    
    # CORS
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])
    
    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v
    
    model_config = {"env_prefix": "API_"}


class Settings(BaseSettings):
    """Main application settings combining all configuration."""
    
    # Environment
    environment: str = Field(default="development")
    debug: bool = Field(default=True)
    
    # Component settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    guardrails: GuardrailsSettings = Field(default_factory=GuardrailsSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    api: APISettings = Field(default_factory=APISettings)
    
    @field_validator('environment')
    @classmethod
    def validate_environment(cls, v):
        allowed = ['development', 'staging', 'production']
        if v not in allowed:
            raise ValueError(f'Environment must be one of: {allowed}')
        return v
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Dependency injection for FastAPI."""
    return settings