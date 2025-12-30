#!/usr/bin/env python3
"""
Entrypoint for the Secure Enterprise AI Agent.
Runs the FastAPI application with proper configuration.
"""

if __name__ == "__main__":
    import uvicorn
    from app.config import get_settings
    
    settings = get_settings()
    
    print(f"🚀 Starting Secure Enterprise AI Agent")
    print(f"📍 Host: {settings.api.host}")
    print(f"🔌 Port: {settings.api.port}")
    print(f"🔒 Guardrails: {'Enabled' if settings.guardrails.enable_by_default else 'Disabled'}")
    print(f"🤖 LLM: {'Mock' if settings.llm.use_mock_llm else 'OpenAI'}")
    print(f"🌍 Environment: {settings.environment}")
    print(f"📚 Docs: http://{settings.api.host}:{settings.api.port}/docs")
    print()
    
    uvicorn.run(
        "app.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload and settings.environment == "development",
        log_level=settings.observability.log_level.lower(),
        access_log=True
    )
