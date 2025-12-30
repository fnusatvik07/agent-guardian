"""API module for FastAPI endpoints."""

from .chat import router as chat_router

__all__ = ["chat_router"]