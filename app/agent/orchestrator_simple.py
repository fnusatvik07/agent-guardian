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
from app.observability import get_logger, agent_logger, guardrails_logger
from app.security import User
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
        self.logger = get_logger("orchestrator")
        self.agent = simple_agent
    
    async def process_request(self, request: AgentRequest) -> Dict[str, Any]:
        """Process agent request with optional guardrails."""
        start_time = time.time()
        trace_id = str(uuid.uuid4())
        
        self.logger.info(f"🚀 REQUEST START: User='{request.user_id}', Role='{request.role}', Guardrails={request.enable_guardrails}")
        self.logger.info(f"🗣️ USER QUERY: '{request.message}'")
        self.logger.info(f"🔍 TRACE ID: {trace_id}")
        
        try:
            # Create simple user context
            from app.security.rbac import Role
            user = User(user_id=request.user_id, role=Role(request.role))
            self.logger.info(f"👤 USER CONTEXT: Created user with role={user.role.value}")
            
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
            violations = []
            
            if request.enable_guardrails and final_content:
                self.logger.info("🛡️ GUARDRAILS: Validating output content")
                output_result = await guardrails_engine.evaluate_output(
                    final_content, user, trace_id
                )
                
                if not output_result.allowed:
                    self.logger.warning(f"🚫 OUTPUT BLOCKED: Violations={output_result.violations}")
                    final_content = "I cannot provide that information due to content policy restrictions."
                    violations.extend(output_result.violations)
                elif output_result.modified_content != final_content:
                    # Apply redacted content
                    final_content = output_result.modified_content
                    violations.extend([v for v in output_result.violations if 'pii' in v.lower()])
                    self.logger.info("🔒 GUARDRAILS: Applied content redaction")
                
                self.logger.info("✅ GUARDRAILS: Output validation complete")
            
            processing_time = (time.time() - start_time) * 1000
            
            # Format response
            return {
                "reply": final_content or "I couldn't generate a response.",
                "status": ResponseStatus.SUCCESS.value,
                "guardrails_enabled": request.enable_guardrails,
                "blocked": False,
                "violations": violations,
                "tool_calls": agent_response.tool_calls,
                "trace_id": trace_id,
                "metadata": {
                    "processing_time_ms": processing_time,
                    "framework": "langchain",
                    "mode": AgentMode.GUARDED.value if request.enable_guardrails else AgentMode.UNGUARDED.value,
                    "tools_used": len(agent_response.tool_calls),
                    "agent_metadata": agent_response.metadata
                },
                "timestamp": time.time()
            }
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            error_msg = str(e)
            
            self.logger.error(f"🚨 REQUEST ERROR: Agent processing failed - {error_msg}")
            self.logger.error(f"🚨 ERROR TYPE: {type(e).__name__}")
            
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
                    "error": error_msg,
                    "error_type": type(e).__name__,
                    "framework": "langchain"
                },
                "timestamp": time.time()
            }


# Create global instance
agent_orchestrator = AgentOrchestrator()