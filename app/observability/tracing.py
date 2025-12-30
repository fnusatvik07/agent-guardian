"""
Distributed tracing implementation for request correlation across services.
Supports OpenTelemetry standards for enterprise observability.
"""
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from contextlib import contextmanager

from app.observability.logger import get_logger, trace_manager


class Span:
    """Represents a single operation trace span."""
    
    def __init__(
        self, 
        name: str, 
        parent_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ):
        self.span_id = trace_manager.generate_trace_id()[:8]  # Shorter span ID
        self.name = name
        self.parent_id = parent_id
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.tags = tags or {}
        self.logs: List[Dict[str, Any]] = []
        self.error: Optional[str] = None
        
        self.logger = get_logger("tracing")
    
    def add_tag(self, key: str, value: Any):
        """Add a tag to the span."""
        self.tags[key] = value
    
    def log_event(self, message: str, **kwargs):
        """Log an event within the span."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "message": message,
            **kwargs
        }
        self.logs.append(event)
    
    def set_error(self, error: str):
        """Mark span as having an error."""
        self.error = error
        self.add_tag("error", True)
    
    def finish(self):
        """Finish the span and log the trace."""
        self.end_time = time.time()
        duration_ms = (self.end_time - self.start_time) * 1000
        
        self.logger.info(
            f"Span completed: {self.name}",
            span_id=self.span_id,
            parent_id=self.parent_id,
            name=self.name,
            duration_ms=round(duration_ms, 2),
            tags=self.tags,
            logs=self.logs,
            error=self.error,
            event_type="span_complete"
        )


class Tracer:
    """Manages distributed tracing for the application."""
    
    def __init__(self):
        self.active_spans: Dict[str, Span] = {}
    
    def start_span(
        self, 
        name: str, 
        parent_id: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ) -> Span:
        """Start a new tracing span."""
        span = Span(name, parent_id, tags)
        self.active_spans[span.span_id] = span
        return span
    
    def finish_span(self, span_id: str):
        """Finish and remove a span."""
        if span_id in self.active_spans:
            span = self.active_spans.pop(span_id)
            span.finish()
    
    @contextmanager
    def trace(self, name: str, **tags):
        """Context manager for tracing operations."""
        span = self.start_span(name, tags=tags)
        try:
            yield span
        except Exception as e:
            span.set_error(str(e))
            raise
        finally:
            self.finish_span(span.span_id)


# Global tracer instance
tracer = Tracer()


def trace_operation(operation_name: str, **tags):
    """Decorator for tracing function calls."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with tracer.trace(f"{func.__module__}.{func.__name__}", operation=operation_name, **tags) as span:
                try:
                    result = func(*args, **kwargs)
                    span.add_tag("success", True)
                    return result
                except Exception as e:
                    span.set_error(f"{type(e).__name__}: {str(e)}")
                    raise
        return wrapper
    return decorator