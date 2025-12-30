"""
Enterprise-grade structured logging with PII redaction and trace correlation.
Follows industry standards for security and compliance.
"""
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from contextvars import ContextVar

import structlog
from structlog.processors import JSONRenderer

from app.config import get_settings

# Context variables for request tracing
trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar('user_id', default=None)


class PIIRedactor:
    """Redacts PII from logs based on configurable patterns."""
    
    def __init__(self, patterns: List[str]):
        self.patterns = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    
    def redact(self, text: str) -> str:
        """Replace PII with [REDACTED] placeholders."""
        if not isinstance(text, str):
            return text
            
        for pattern in self.patterns:
            text = pattern.sub('[REDACTED]', text)
        return text
    
    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact PII from dictionary values."""
        if not isinstance(data, dict):
            return data
            
        redacted = {}
        for key, value in data.items():
            if isinstance(value, str):
                redacted[key] = self.redact(value)
            elif isinstance(value, dict):
                redacted[key] = self.redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self.redact_dict(item) if isinstance(item, dict) 
                    else self.redact(item) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                redacted[key] = value
        return redacted


def add_trace_context(logger, method_name, event_dict):
    """Add trace ID and user context to all log events."""
    trace_id = trace_id_var.get()
    user_id = user_id_var.get()
    
    if trace_id:
        event_dict['trace_id'] = trace_id
    if user_id:
        event_dict['user_id'] = user_id
    
    event_dict['timestamp'] = datetime.utcnow().isoformat()
    event_dict['service'] = 'governance-agent'
    
    return event_dict


def redact_pii_processor(logger, method_name, event_dict):
    """Process log events to redact PII."""
    settings = get_settings()
    redactor = PIIRedactor(settings.security.pii_patterns)
    
    # Redact the main message
    if 'event' in event_dict:
        event_dict['event'] = redactor.redact(str(event_dict['event']))
    
    # Redact any additional data
    for key, value in list(event_dict.items()):
        if key not in ['timestamp', 'trace_id', 'user_id', 'service', 'level']:
            if isinstance(value, str):
                event_dict[key] = redactor.redact(value)
            elif isinstance(value, dict):
                event_dict[key] = redactor.redact_dict(value)
    
    return event_dict


def configure_logging():
    """Configure structured logging with PII redaction."""
    settings = get_settings()
    
    processors = [
        add_trace_context,
        redact_pii_processor,
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
    ]
    
    if settings.observability.log_format == "json":
        processors.append(JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog.stdlib, settings.observability.log_level.upper(), 20)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__):
    """Get a configured logger instance."""
    return structlog.get_logger(name)


class TraceManager:
    """Manages request tracing and context correlation."""
    
    @staticmethod
    def generate_trace_id() -> str:
        """Generate a new trace ID."""
        return str(uuid.uuid4())
    
    @staticmethod
    def set_trace_context(trace_id: str, user_id: Optional[str] = None):
        """Set trace context for the current request."""
        trace_id_var.set(trace_id)
        if user_id:
            user_id_var.set(user_id)
    
    @staticmethod
    def get_trace_id() -> Optional[str]:
        """Get the current trace ID."""
        return trace_id_var.get()
    
    @staticmethod
    def clear_context():
        """Clear trace context."""
        trace_id_var.set(None)
        user_id_var.set(None)


class GuardrailsLogger:
    """Specialized logger for guardrails decisions and violations."""
    
    def __init__(self):
        self.logger = get_logger("guardrails")
    
    def log_violation(
        self, 
        violation_type: str, 
        message: str, 
        blocked: bool = True,
        details: Optional[Dict[str, Any]] = None
    ):
        """Log a guardrails violation with structured data."""
        self.logger.warning(
            "Guardrails violation detected",
            violation_type=violation_type,
            message=message,
            blocked=blocked,
            details=details or {},
            event_type="guardrails_violation"
        )
    
    def log_decision(
        self, 
        decision: str, 
        reasoning: str, 
        input_safe: bool = True,
        output_safe: bool = True
    ):
        """Log a guardrails decision."""
        self.logger.info(
            "Guardrails decision made",
            decision=decision,
            reasoning=reasoning,
            input_safe=input_safe,
            output_safe=output_safe,
            event_type="guardrails_decision"
        )
    
    def log_bypass(self, reason: str):
        """Log when guardrails are bypassed."""
        self.logger.warning(
            "Guardrails bypassed",
            reason=reason,
            event_type="guardrails_bypass"
        )


class AgentLogger:
    """Specialized logger for agent operations."""
    
    def __init__(self):
        self.logger = get_logger("agent")
    
    def log_tool_call(
        self, 
        tool_name: str, 
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None
    ):
        """Log tool calls with arguments and results."""
        self.logger.info(
            f"Tool call: {tool_name}",
            tool_name=tool_name,
            args=args,
            success=error is None,
            error=error,
            event_type="tool_call"
        )
    
    def log_llm_call(
        self, 
        model: str,
        prompt_length: int,
        response_length: int,
        tokens_used: Optional[int] = None,
        latency_ms: Optional[float] = None
    ):
        """Log LLM API calls with metrics."""
        self.logger.info(
            f"LLM call to {model}",
            model=model,
            prompt_length=prompt_length,
            response_length=response_length,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            event_type="llm_call"
        )


# Initialize logging on module import
configure_logging()

# Export commonly used instances
trace_manager = TraceManager()
guardrails_logger = GuardrailsLogger()
agent_logger = AgentLogger()