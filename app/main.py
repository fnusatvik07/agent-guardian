"""
Main FastAPI application for the Secure Enterprise AI Agent.
Integrates all components with comprehensive middleware and security.
"""
import time
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from app.config import get_settings
from app.observability import get_logger, trace_manager, configure_logging
from app.api import chat_router

# Configure logging first
configure_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    
    # Startup
    logger.info("Starting Governance Agent application")
    
    try:
        # Initialize components
        from app.agent import agent_orchestrator
        from app.guardrails import guardrails_engine
        
        # Perform health check on startup
        health = await agent_orchestrator.health_check()
        logger.info(
            "Application startup completed",
            health_status=health["status"],
            components=list(health["components"].keys())
        )
        
        # Create sample documents and data if needed
        await _initialize_sample_data()
        
    except Exception as e:
        logger.error(f"Application startup failed: {str(e)}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Governance Agent application")


async def _initialize_sample_data():
    """Initialize sample data for demo purposes."""
    try:
        # This would initialize sample documents, users, etc.
        # Already handled by individual components in their __init__ methods
        logger.info("Sample data initialization completed")
    except Exception as e:
        logger.warning(f"Sample data initialization failed: {str(e)}")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    
    settings = get_settings()
    
    # Create FastAPI app
    app = FastAPI(
        title="Secure Enterprise AI Agent",
        description="""
        Production-grade AI Agent with NeMo Guardrails integration.
        
        ## Features
        
        * **Guardrails Toggle**: Enable/disable security guardrails to demonstrate differences
        * **Role-Based Access**: Employee and admin roles with different tool access
        * **Enterprise Tools**: Knowledge base search, ticketing, database queries, web search
        * **Security**: PII detection, prompt injection protection, tool access control
        * **Observability**: Comprehensive logging, tracing, and monitoring
        
        ## Roles
        
        * **Employee**: Can use knowledge base search, create tickets, web search
        * **Admin**: All employee tools plus user profiles, database queries, sensitive documents
        
        ## Guardrails
        
        * **Enabled**: Full security validation, PII protection, access control
        * **Disabled**: Direct LLM access for demonstration purposes
        
        ## Security Features
        
        * Prompt injection detection
        * Jailbreak attempt prevention  
        * PII detection and redaction
        * Role-based tool access
        * SQL injection prevention
        * Output content validation
        """,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )
    
    # Add security middleware
    if settings.environment == "production":
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["localhost", "127.0.0.1", "*.your-domain.com"]
        )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add custom middleware
    app.middleware("http")(request_middleware)
    app.middleware("http")(rate_limiting_middleware)
    
    # Add exception handlers
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    # Include routers
    app.include_router(chat_router)
    
    # Add root endpoint
    @app.get("/", tags=["root"])
    async def root() -> Dict[str, Any]:
        """Root endpoint with API information."""
        return {
            "message": "Secure Enterprise AI Agent API",
            "version": "0.1.0",
            "status": "operational",
            "docs": "/docs",
            "health": "/api/v1/health",
            "features": {
                "guardrails_toggle": True,
                "role_based_access": True,
                "enterprise_tools": True,
                "observability": True
            }
        }
    
    return app


async def request_middleware(request: Request, call_next):
    """Request middleware for tracing and logging."""
    
    start_time = time.time()
    trace_id = trace_manager.generate_trace_id()
    trace_manager.set_trace_context(trace_id)
    
    # Add trace ID to response headers
    response = await call_next(request)
    
    processing_time = time.time() - start_time
    
    # Add custom headers
    response.headers["X-Trace-ID"] = trace_id
    response.headers["X-Processing-Time"] = str(round(processing_time * 1000, 2))
    
    # Log request
    logger.info(
        "Request processed",
        method=request.method,
        url=str(request.url),
        status_code=response.status_code,
        processing_time_ms=round(processing_time * 1000, 2),
        client_ip=request.client.host if request.client else "unknown"
    )
    
    return response


async def rate_limiting_middleware(request: Request, call_next):
    """Basic rate limiting middleware."""
    
    settings = get_settings()
    
    if not settings.api.rate_limit_enabled:
        return await call_next(request)
    
    # Simple in-memory rate limiting (use Redis in production)
    client_ip = request.client.host if request.client else "unknown"
    
    # For demo purposes, we'll skip actual rate limiting implementation
    # In production, use Redis with sliding window or token bucket
    
    return await call_next(request)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with proper logging."""
    
    logger.warning(
        "HTTP exception occurred",
        status_code=exc.status_code,
        detail=exc.detail,
        url=str(request.url),
        method=request.method
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "type": "HTTPException",
                "status_code": exc.status_code,
                "message": exc.detail,
                "trace_id": trace_manager.get_trace_id()
            }
        }
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle general exceptions with proper logging and security."""
    
    logger.error(
        "Unhandled exception occurred",
        error_type=type(exc).__name__,
        error_message=str(exc),
        url=str(request.url),
        method=request.method
    )
    
    # Don't expose internal error details in production
    settings = get_settings()
    
    if settings.environment == "production":
        error_message = "An internal error occurred. Please try again or contact support."
    else:
        error_message = str(exc)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "type": "InternalError",
                "status_code": 500,
                "message": error_message,
                "trace_id": trace_manager.get_trace_id()
            }
        }
    )


# Create the application instance
app = create_application()


if __name__ == "__main__":
    settings = get_settings()
    
    uvicorn.run(
        "app.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        log_level=settings.observability.log_level.lower(),
        access_log=True
    )