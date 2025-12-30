"""
Simple agent orchestrator.
"""
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import uuid

from app.config import get_settings
from app.observability import get_logger, agent_logger
from app.security import User, rbac_manager, Permission
from app.agent.langchain_simple import simple_agent
from app.guardrails import guardrails_engine


class AgentMode(str, Enum):
    """Agent operation modes."""
    GUARDED = "guarded"
    UNGUARDED = "unguarded"


class ResponseStatus(str, Enum):
    """Status of agent response.""" 
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass
class AgentRequest:
    """Agent request format."""
    user_id: str
    message: str
    role: str
    enable_guardrails: bool = True
    conversation_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    max_tool_calls: int = 5
    
    def __post_init__(self):
        if self.conversation_id is None:
            self.conversation_id = str(uuid.uuid4())
        if self.context is None:
            self.context = {}


class AgentOrchestrator:
    """Simple agent orchestrator."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger("agent_orchestrator")
        self.agent = simple_agent
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check for the orchestrator."""
        return {
            "status": "healthy",
            "components": {
                "agent": "healthy",
                "langchain": "healthy"
            },
            "timestamp": time.time()
        }
    
    async def process_request(self, request: AgentRequest) -> Dict[str, Any]:
        """Process agent request with optional guardrails and detailed logging."""
        start_time = time.time()
        trace_id = str(uuid.uuid4())
        
        self.logger.info(f"🚀 REQUEST START: User='{request.user_id}', Role='{request.role}', Guardrails={request.enable_guardrails}")
        self.logger.info(f"🗣️ USER QUERY: '{request.message}'")
        self.logger.info(f"🔍 TRACE ID: {trace_id}")
        
        try:
            # Create user context
            user = rbac_manager.create_user(request.user_id, request.role)
            self.logger.info(f"👤 USER CONTEXT: Created user with role={user.role.value}")
            
            # Validate permissions
            if not rbac_manager.check_permission(user, Permission.USE_SEARCH_TOOLS):
                self.logger.warning(f"🚫 ACCESS DENIED: User '{request.user_id}' with role '{request.role}' lacks chat permissions")
                return {
                    "reply": "Access denied. Insufficient permissions.",
                    "status": ResponseStatus.BLOCKED.value,
                    "guardrails_enabled": request.enable_guardrails,
                    "blocked": True,
                    "violations": ["insufficient_permissions"],
                    "tool_calls": [],
                    "trace_id": trace_id,
                    "metadata": {"error": "Access denied"},
                    "timestamp": time.time()
                }
            
            self.logger.info("✅ RBAC CHECK: User has chat permissions")
            
            # Input guardrails check
            if request.enable_guardrails:
                self.logger.info("🛡️ GUARDRAILS: Validating input content")
                guardrails_result = await guardrails_engine.evaluate_input(
                    request.message, user, trace_id
                )
                if not guardrails_result.allowed:
                    self.logger.warning(f"🚫 INPUT BLOCKED: Violations={guardrails_result.violations}")
                    return {
                        "reply": "Your request was blocked by content policy.",
                        "status": ResponseStatus.BLOCKED.value,
                        "guardrails_enabled": True,
                        "blocked": True,
                        "violations": guardrails_result.violations,
                        "tool_calls": [],
                        "trace_id": trace_id,
                        "metadata": {"blocked_reason": guardrails_result.violations},
                        "timestamp": time.time()
                    }
                self.logger.info("✅ GUARDRAILS: Input validation passed")
            else:
                self.logger.info("⚠️ GUARDRAILS: Bypassed (unguarded mode)")
            
            # Process with agent
            self.logger.info("🤖 AGENT PROCESSING: Sending to LangChain agent")
            messages = [{"role": "user", "content": request.message}]
            agent_response = await self.agent.chat_completion(messages)
            self.logger.info(f"✅ AGENT COMPLETE: Generated response with {len(agent_response.content or '')} characters")
            
            # Output guardrails check
            final_content = agent_response.content
            if request.enable_guardrails and final_content:
                self.logger.info("🛡️ GUARDRAILS: Validating output content")
                guardrails_result = await guardrails_engine.evaluate_output(
                    final_content, user, trace_id
                )
                if not guardrails_result.allowed:
                    self.logger.warning(f"🚫 OUTPUT BLOCKED: Violations={guardrails_result.violations}")
                    final_content = "Response was blocked by content policy."
                else:
                    self.logger.info("✅ GUARDRAILS: Output validation passed")
            
            processing_time = (time.time() - start_time) * 1000
            self.logger.info(f"🎯 REQUEST COMPLETE: Processing took {processing_time:.2f}ms")
            
            return {
                "reply": final_content,
                "status": ResponseStatus.SUCCESS.value,
                "guardrails_enabled": request.enable_guardrails,
                "blocked": False,
                "violations": [],
                "tool_calls": agent_response.tool_calls or [],
                "trace_id": trace_id,
                "metadata": {
                    "processing_time_ms": processing_time,
                    "framework": "langchain",
                    "mode": "guarded" if request.enable_guardrails else "unguarded",
                    "tools_used": len(agent_response.tool_calls or []),
                    "agent_metadata": getattr(agent_response, 'metadata', {})
                },
                "timestamp": time.time()
            }
            
        except Exception as e:
            self.logger.error(f"🚨 REQUEST ERROR: Agent processing failed - {str(e)}")
            self.logger.error(f"🚨 ERROR TYPE: {type(e).__name__}")
            processing_time = (time.time() - start_time) * 1000
            
            return {
                "reply": "I apologize, but I encountered an error processing your request. Please try again or contact support if the problem persists.",
                "status": ResponseStatus.ERROR.value,
                "guardrails_enabled": request.enable_guardrails,
                "blocked": False,
                "violations": [],
                "tool_calls": [],
                "trace_id": trace_id,
                "metadata": {
                    "processing_time_ms": processing_time,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "framework": "langchain"
                },
                "timestamp": time.time()
            }


# Global instance
agent_orchestrator = AgentOrchestrator()