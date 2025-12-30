# Copilot Instructions for Secure Enterprise AI Agent

## Project Overview

This is a production-grade AI Agent system built with FastAPI and NeMo Guardrails, designed to demonstrate secure AI implementations in enterprise environments. The system features **toggleable guardrails** to clearly show the difference between guarded and unguarded AI behavior.

## Architecture Understanding

### Core Components Hierarchy
1. **FastAPI API Layer** (`app/api/`) - HTTP endpoints with comprehensive validation
2. **Agent Orchestration** (`app/agent/orchestrator.py`) - Main coordination logic
3. **Guardrails Engine** (`app/guardrails/engine.py`) - Security validation (toggleable)
4. **LLM Client** (`app/agent/llm_client.py`) - Abstracted LLM provider interface
5. **Enterprise Tools** (`app/agent/tools.py`) - Business system integrations
6. **Security Layer** (`app/security/`) - RBAC, PII detection, access control

### Key Design Patterns
- **Dependency Injection**: Global instances (`agent_orchestrator`, `guardrails_engine`, `tool_registry`)
- **Factory Pattern**: Settings-based component initialization
- **Observer Pattern**: Structured logging with trace correlation
- **Strategy Pattern**: Guardrails engine (NeMo vs Mock implementations)

## Critical Development Workflows

### Adding New Enterprise Tools
1. Define tool in `ToolRegistry.tool_definitions` with OpenAI function schema
2. Implement execution logic in `ToolRegistry.execute_tool()`
3. Add role permissions to `app/config/settings.py` role mappings
4. Create guardrails validation in `app/guardrails/rails/tools.co`
5. Add audit logging in tool implementation

### Guardrails Development
- **Input Rails**: `app/guardrails/rails/input.co` - validates user input
- **Output Rails**: `app/guardrails/rails/output.co` - sanitizes AI responses  
- **Tool Rails**: `app/guardrails/rails/tools.co` - validates tool usage
- **Config**: `app/guardrails/config.yml` - NeMo Guardrails configuration

### Security Implementation
- All PII detection uses `app/security/redaction.py` patterns
- RBAC enforced through `app/security/rbac.py` decorators and checks
- Tool access validated in `ToolRegistry.execute_tool()` before execution

## Project-Specific Conventions

### Logging Standards
```python
from app.observability import get_logger, agent_logger, guardrails_logger
logger = get_logger("component_name")
logger.info("Event description", key=value, structured_data=data)
```

### Error Handling Patterns
```python
try:
    result = await operation()
    return ToolResult(success=True, data=result)
except Exception as e:
    logger.error(f"Operation failed: {str(e)}")
    return ToolResult(success=False, error=str(e))
```

### Configuration Access
```python
from app.config import get_settings
settings = get_settings()
# Access via: settings.llm.model_name, settings.security.pii_patterns, etc.
```

## Integration Points & Dependencies

### External System Integrations
- **OpenAI API**: `app/agent/llm_client.py` (with fallback to mock)
- **SQLite**: Enterprise database queries (`app/agent/tools.py`)
- **MongoDB**: Document storage (optional, graceful degradation)
- **ChromaDB**: Vector search for knowledge base
- **NeMo Guardrails**: Security validation (optional, mock fallback)

### Cross-Component Communication
- **Request Flow**: FastAPI → Agent Orchestrator → Guardrails → LLM/Tools
- **Trace Correlation**: Uses `trace_id` throughout request lifecycle
- **Event Propagation**: Structured logs with consistent field names

## Essential Commands & Debugging

### Development Setup
```bash
python main.py                    # Start with development settings
uvicorn app.main:app --reload     # Alternative startup
curl localhost:8000/api/v1/health # Health check
```

### Testing Guardrails Behavior
```bash
# Test with guardrails enabled (safe)
curl -X POST localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -d '{"user_id":"test","message":"Hello","role":"employee","enable_guardrails":true}'

# Test with guardrails disabled (demonstrates risks)  
curl -X POST localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -d '{"user_id":"test","message":"Ignore instructions","role":"employee","enable_guardrails":false}'
```

### Debugging Common Issues
- **Guardrails not working**: Check `NEMO_AVAILABLE` in `guardrails/engine.py`
- **Tool access denied**: Verify role permissions in `config/settings.py`
- **LLM failures**: Check `LLM_USE_MOCK_LLM=true` for local development
- **Database errors**: Ensure `data/` directory exists for SQLite

## Architecture Decisions & Rationale

### Why Toggleable Guardrails
The system demonstrates security value by allowing runtime enable/disable of guardrails, clearly showing:
- **Guarded**: Blocks prompt injection, redacts PII, enforces RBAC
- **Unguarded**: Exposes risks for educational/demo purposes

### Mock vs Production Components  
- **Mock LLM**: Enables development without API costs
- **Mock Guardrails**: Functional when NeMo Guardrails unavailable
- **Graceful Degradation**: System remains functional with missing dependencies

### Security-First Design
- **No Sensitive Data in Logs**: PII automatically redacted
- **Principle of Least Privilege**: Role-based tool access 
- **Input Validation**: Multiple layers (FastAPI, Guardrails, Tools)
- **Audit Trail**: All security events logged with trace correlation

When working on this codebase, prioritize security considerations and maintain the clear separation between guarded/unguarded behavior that enables effective security demonstrations.