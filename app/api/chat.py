"""
FastAPI chat endpoint with comprehensive request/response handling.
Implements the main chat interface with guardrails toggle and proper validation.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, validator

from app.config import get_settings, Settings
from app.observability import get_logger, trace_manager, tracer
from app.agent import agent_orchestrator, AgentRequest, AgentMode, ResponseStatus
from app.security import rbac_manager

# Initialize router
router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = get_logger("chat_api")


# Request/Response Models
class ChatRequestModel(BaseModel):
    """Chat request model with comprehensive validation."""
    user_id: str = Field(..., description="Unique user identifier", min_length=1, max_length=100)
    message: str = Field(..., description="User message", min_length=1, max_length=10000)
    role: str = Field(..., description="User role (employee, admin)", pattern="^(employee|admin)$")
    enable_guardrails: bool = Field(True, description="Whether to enable guardrails")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for context")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional context")
    max_tool_calls: int = Field(5, description="Maximum tool calls allowed", ge=0, le=10)
    
    @validator('message')
    def validate_message(cls, v):
        if not v.strip():
            raise ValueError('Message cannot be empty or only whitespace')
        return v.strip()
    
    @validator('context')
    def validate_context(cls, v):
        if v is None:
            return {}
        # Ensure context doesn't contain sensitive keys
        sensitive_keys = ['password', 'token', 'secret', 'key']
        for key in v.keys():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                raise ValueError(f'Context cannot contain sensitive key: {key}')
        return v


class ViolationModel(BaseModel):
    """Guardrails violation model."""
    type: str = Field(..., description="Violation type")
    severity: str = Field(..., description="Violation severity")
    message: str = Field(..., description="Violation description")
    blocked: bool = Field(..., description="Whether the violation was blocked")
    recommendation: Optional[str] = Field(None, description="Recommended action")


class ToolCallModel(BaseModel):
    """Tool call summary model."""
    tool: str = Field(..., description="Tool name")
    success: bool = Field(..., description="Whether tool call succeeded")
    error: Optional[str] = Field(None, description="Error message if failed")


class ChatResponseModel(BaseModel):
    """Chat response model with comprehensive metadata."""
    reply: str = Field(..., description="AI assistant response")
    status: str = Field(..., description="Response status")
    guardrails_enabled: bool = Field(..., description="Whether guardrails were enabled")
    blocked: bool = Field(False, description="Whether request was blocked")
    violations: List[ViolationModel] = Field(default_factory=list, description="Guardrails violations")
    tool_calls: List[ToolCallModel] = Field(default_factory=list, description="Tool calls made")
    trace_id: str = Field(..., description="Trace ID for request correlation")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    
    class Config:
        schema_extra = {
            "example": {
                "reply": "I can help you search our knowledge base. What information are you looking for?",
                "status": "success", 
                "guardrails_enabled": True,
                "blocked": False,
                "violations": [],
                "tool_calls": [
                    {
                        "tool": "search_internal_kb",
                        "success": True,
                        "error": None
                    }
                ],
                "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                "metadata": {
                    "processing_time_ms": 1250.5,
                    "llm_provider": "openai",
                    "tools_used": 1
                },
                "timestamp": "2024-01-01T12:00:00Z"
            }
        }


class HealthCheckModel(BaseModel):
    """Health check response model."""
    status: str = Field(..., description="Overall system health")
    timestamp: float = Field(..., description="Timestamp of health check")
    components: Dict[str, str] = Field(..., description="Component health status")
    version: str = Field(..., description="Application version")


class SystemInfoModel(BaseModel):
    """System information response model."""
    llm_provider: Dict[str, Any] = Field(..., description="LLM provider information")
    guardrails: Dict[str, Any] = Field(..., description="Guardrails configuration")
    tools_available: int = Field(..., description="Number of available tools")
    conversation_manager: Dict[str, Any] = Field(..., description="Conversation manager status")


# Dependency Functions
def get_request_context(request: Request) -> Dict[str, Any]:
    """Extract request context for logging and tracing."""
    return {
        "client_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "request_id": str(uuid.uuid4())
    }


# API Endpoints
@router.post(
    "/chat",
    response_model=ChatResponseModel,
    summary="Chat with AI Assistant",
    description="""
    Send a message to the AI assistant with optional guardrails.
    
    The assistant can use various tools based on your role:
    - **Employee**: Knowledge base search, ticket creation, web search
    - **Admin**: All employee tools plus user profiles, database queries
    
    Guardrails can be enabled/disabled to demonstrate security differences:
    - **Enabled**: Full security validation and PII protection
    - **Disabled**: Direct LLM access (for demo purposes)
    """,
    responses={
        200: {"description": "Successful response"},
        400: {"description": "Invalid request"},
        403: {"description": "Access forbidden"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"}
    }
)
async def chat(
    request_data: ChatRequestModel,
    request_context: Dict[str, Any] = Depends(get_request_context),
    settings: Settings = Depends(get_settings)
) -> ChatResponseModel:
    """Main chat endpoint with guardrails toggle."""
    
    with tracer.trace("chat_endpoint") as span:
        span.add_tag("user_id", request_data.user_id)
        span.add_tag("role", request_data.role)
        span.add_tag("guardrails_enabled", request_data.enable_guardrails)
        span.add_tag("message_length", len(request_data.message))
        
        try:
            # Create agent request
            agent_request = AgentRequest(
                user_id=request_data.user_id,
                message=request_data.message,
                role=request_data.role,
                enable_guardrails=request_data.enable_guardrails,
                conversation_id=request_data.conversation_id,
                context={**request_data.context, **request_context},
                max_tool_calls=request_data.max_tool_calls
            )
            
            # Determine agent mode based on guardrails setting
            if request_data.enable_guardrails:
                mode = AgentMode.GUARDED
            else:
                mode = AgentMode.UNGUARDED
            
            # Process chat request
            agent_response = await agent_orchestrator.process_request(agent_request)
            
            # Convert to API response model
            violations = []
            for v in agent_response.get("violations", []):
                if isinstance(v, str):
                    violations.append(ViolationModel(
                        type=v,
                        severity="medium", 
                        message=v,
                        blocked=True,
                        recommendation=None
                    ))
                elif isinstance(v, dict):
                    violations.append(ViolationModel(
                        type=v.get("type", "unknown"),
                        severity=v.get("severity", "medium"),
                        message=v.get("message", "Violation detected"),
                        blocked=v.get("blocked", True),
                        recommendation=v.get("recommendation")
                    ))

            tool_calls = [
                ToolCallModel(
                    tool=tc.get("tool", "unknown"),
                    success=tc.get("success", False),
                    error=tc.get("error")
                )
                for tc in agent_response.get("tool_calls", [])
            ]

            response = ChatResponseModel(
                reply=agent_response.get("reply", ""),
                status=agent_response.get("status", "error"),
                guardrails_enabled=agent_response.get("guardrails_enabled", False),
                blocked=agent_response.get("blocked", False),
                violations=violations,
                tool_calls=tool_calls,
                trace_id=agent_response.get("trace_id", "unknown"),
                metadata=agent_response.get("metadata", {})
            )
            
            logger.info(
                "Chat request processed",
                user_id=request_data.user_id,
                status=agent_response.get("status", "error"),
                violations=len(violations),
                tools_used=len(tool_calls)
            )
            
            span.add_tag("success", True)
            span.add_tag("response_status", agent_response.get("status", "error"))
            
            return response
            
        except ValueError as e:
            logger.warning(
                "Invalid chat request",
                user_id=request_data.user_id,
                error=str(e)
            )
            span.set_error(str(e))
            raise HTTPException(status_code=400, detail=str(e))
            
        except PermissionError as e:
            logger.warning(
                "Permission denied for chat request",
                user_id=request_data.user_id,
                error=str(e)
            )
            span.set_error(str(e))
            raise HTTPException(status_code=403, detail=str(e))
            
        except Exception as e:
            logger.error(
                "Chat request failed",
                user_id=request_data.user_id,
                error=str(e),
                error_type=type(e).__name__
            )
            span.set_error(str(e))
            raise HTTPException(
                status_code=500, 
                detail="Internal server error. Please try again or contact support."
            )


@router.get(
    "/health",
    response_model=HealthCheckModel,
    summary="Health Check",
    description="Check the health status of all system components"
)
async def health_check() -> HealthCheckModel:
    """Health check endpoint for monitoring."""
    
    try:
        health_data = await agent_orchestrator.health_check()
        
        return HealthCheckModel(
            status=health_data["status"],
            timestamp=health_data["timestamp"],
            components=health_data["components"],
            version="0.1.0"  # From pyproject.toml
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Health check failed"
        )


@router.get(
    "/system/info",
    response_model=SystemInfoModel,
    summary="System Information",
    description="Get detailed information about system capabilities and configuration"
)
async def system_info() -> SystemInfoModel:
    """System information endpoint."""
    
    try:
        info = agent_orchestrator.get_system_info()
        
        return SystemInfoModel(
            llm_provider=info["llm_provider"],
            guardrails=info["guardrails"],
            tools_available=info["tools_available"],
            conversation_manager=info["conversation_manager"]
        )
        
    except Exception as e:
        logger.error(f"System info request failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve system information"
        )


@router.get(
    "/tools",
    summary="Available Tools",
    description="Get list of tools available to the specified user role"
)
async def get_available_tools(
    role: str,
    user_id: str = "demo_user"
) -> Dict[str, Any]:
    """Get available tools for a user role."""
    
    try:
        # Validate role
        if role not in ["employee", "admin"]:
            raise HTTPException(status_code=400, detail="Invalid role. Must be 'employee' or 'admin'")
        
        # Create user object
        user = rbac_manager.create_user(user_id=user_id, role=role)
        
        # Get available tools
        from app.agent.tools import tool_registry
        tools = tool_registry.get_available_tools(user)
        
        return {
            "user_role": role,
            "tools_count": len(tools),
            "tools": tools
        }
        
    except Exception as e:
        logger.error(f"Tools request failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve available tools"
        )


@router.post(
    "/conversations/{conversation_id}/clear",
    summary="Clear Conversation",
    description="Clear conversation history for the specified conversation ID"
)
async def clear_conversation(conversation_id: str) -> Dict[str, str]:
    """Clear conversation history."""
    
    try:
        agent_orchestrator.conversation_manager.clear_conversation(conversation_id)
        
        logger.info(f"Conversation cleared: {conversation_id}")
        
        return {
            "message": f"Conversation {conversation_id} cleared successfully",
            "conversation_id": conversation_id
        }
        
    except Exception as e:
        logger.error(f"Clear conversation failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Unable to clear conversation"
        )