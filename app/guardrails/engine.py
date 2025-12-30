"""
NeMo Guardrails integration engine for enterprise AI safety.
Provides runtime guardrails with configurable enforcement and detailed violation logging.
"""
import os
import json
import asyncio
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

try:
    from nemoguardrails import LLMRails, RailsConfig
    from nemoguardrails.actions import ActionResult
    NEMO_AVAILABLE = True
except ImportError:
    NEMO_AVAILABLE = False
    # Mock classes for when NeMo is not available
    class LLMRails:
        pass
    class RailsConfig:
        pass
    class ActionResult:
        pass

from app.config import get_settings
from app.observability import get_logger, guardrails_logger, trace_operation
from app.security import User, secure_data_handler, PIIMatch
from app.agent.langchain_simple import AgentResponse


class ViolationType(str, Enum):
    """Types of guardrails violations."""
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK_ATTEMPT = "jailbreak_attempt"
    PII_DETECTED = "pii_detected"
    UNAUTHORIZED_TOOL = "unauthorized_tool"
    RESTRICTED_TOPIC = "restricted_topic"
    OUTPUT_PII = "output_pii"
    INFORMATION_LEAKAGE = "information_leakage"
    TOOL_INJECTION = "tool_injection"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


@dataclass
class GuardrailsViolation:
    """Represents a guardrails violation with context."""
    violation_type: ViolationType
    severity: str  # "low", "medium", "high", "critical"
    message: str
    context: Dict[str, Any]
    user_id: Optional[str] = None
    blocked: bool = True
    recommendation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert violation to dictionary format."""
        return {
            "type": self.violation_type.value,
            "severity": self.severity,
            "message": self.message,
            "context": self.context,
            "user_id": self.user_id,
            "blocked": self.blocked,
            "recommendation": self.recommendation
        }


@dataclass
class GuardrailsResult:
    """Result of guardrails evaluation."""
    allowed: bool
    violations: List[GuardrailsViolation]
    modified_content: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "violations": [
                {
                    "type": v.violation_type.value,
                    "severity": v.severity,
                    "message": v.message,
                    "context": v.context,
                    "blocked": v.blocked,
                    "recommendation": v.recommendation
                }
                for v in self.violations
            ],
            "modified_content": self.modified_content,
            "metadata": self.metadata or {}
        }


class MockGuardrailsEngine:
    """Mock guardrails engine for testing without NeMo Guardrails."""
    
    def __init__(self, config_path: str):
        self.logger = get_logger("mock_guardrails")
        self.config_path = config_path
        self.settings = get_settings()
        
        self.logger.info("Mock guardrails engine initialized")
    
    async def evaluate_input(
        self, 
        user_message: str, 
        user: User,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardrailsResult:
        """Mock input evaluation with basic pattern detection."""
        violations = []
        
        # Basic prompt injection detection
        injection_patterns = [
            "ignore previous instructions",
            "you are now",
            "forget everything",
            "new role:",
            "system:"
        ]
        
        for pattern in injection_patterns:
            if pattern in user_message.lower():
                violations.append(GuardrailsViolation(
                    violation_type=ViolationType.PROMPT_INJECTION,
                    severity="high",
                    message=f"Potential prompt injection detected: '{pattern}'",
                    context={"pattern": pattern, "input_length": len(user_message)},
                    user_id=user.user_id,
                    blocked=True,
                    recommendation="Rephrase your request without instruction manipulation."
                ))
                break
        
        # Basic jailbreak detection
        jailbreak_patterns = [
            "pretend you are",
            "act as if", 
            "simulate",
            "roleplay as"
        ]
        
        for pattern in jailbreak_patterns:
            if pattern in user_message.lower():
                violations.append(GuardrailsViolation(
                    violation_type=ViolationType.JAILBREAK_ATTEMPT,
                    severity="high",
                    message=f"Potential jailbreak attempt detected: '{pattern}'",
                    context={"pattern": pattern},
                    user_id=user.user_id,
                    blocked=True,
                    recommendation="Please make straightforward requests without roleplaying."
                ))
                break
        
        # PII detection
        is_safe, pii_matches = secure_data_handler.validate_input_safety(user_message)
        if not is_safe:
            violations.append(GuardrailsViolation(
                violation_type=ViolationType.PII_DETECTED,
                severity="critical",
                message="Sensitive PII detected in input",
                context={"pii_types": [match.pii_type.value for match in pii_matches]},
                user_id=user.user_id,
                blocked=True,
                recommendation="Please remove sensitive information and try again."
            ))
        
        # Check for restricted topics based on user role
        if user.role.value != "admin":
            restricted_topics = [
                "salary", "compensation", "merger", "acquisition",
                "confidential", "classified", "security procedure"
            ]
            
            for topic in restricted_topics:
                if topic in user_message.lower():
                    violations.append(GuardrailsViolation(
                        violation_type=ViolationType.RESTRICTED_TOPIC,
                        severity="medium",
                        message=f"Access to restricted topic '{topic}' denied",
                        context={"topic": topic, "user_role": user.role.value},
                        user_id=user.user_id,
                        blocked=True,
                        recommendation=f"Contact appropriate department for {topic}-related information."
                    ))
                    break
        
        # Determine if request should be allowed
        critical_violations = [v for v in violations if v.severity == "critical"]
        high_violations = [v for v in violations if v.severity == "high"]
        
        allowed = len(critical_violations) == 0 and len(high_violations) == 0
        
        return GuardrailsResult(
            allowed=allowed,
            violations=violations,
            metadata={
                "engine": "mock",
                "input_length": len(user_message),
                "user_role": user.role.value
            }
        )
    
    async def evaluate_output(
        self, 
        bot_response: str, 
        user: User,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardrailsResult:
        """Mock output evaluation with PII redaction."""
        violations = []
        modified_content = bot_response
        
        # Redact PII from output
        redacted_response, pii_matches = secure_data_handler.redactor.redact_text(
            bot_response, preserve_format=False
        )
        
        if pii_matches:
            violations.append(GuardrailsViolation(
                violation_type=ViolationType.OUTPUT_PII,
                severity="high",
                message="PII detected and redacted in output",
                context={"pii_types": [match.pii_type.value for match in pii_matches]},
                user_id=user.user_id,
                blocked=False,  # Modified, not blocked
                recommendation="PII has been automatically redacted."
            ))
            modified_content = redacted_response
        
        # Check for API keys or credentials in output
        credential_patterns = ["sk-", "Bearer ", "password", "api_key"]
        for pattern in credential_patterns:
            if pattern in bot_response:
                violations.append(GuardrailsViolation(
                    violation_type=ViolationType.INFORMATION_LEAKAGE,
                    severity="critical",
                    message="Potential credentials detected in output",
                    context={"pattern": pattern},
                    user_id=user.user_id,
                    blocked=True,
                    recommendation="Response blocked due to potential credential exposure."
                ))
                return GuardrailsResult(
                    allowed=False,
                    violations=violations,
                    metadata={"engine": "mock", "blocked_reason": "credential_exposure"}
                )
        
        return GuardrailsResult(
            allowed=True,
            violations=violations,
            modified_content=modified_content if modified_content != bot_response else None,
            metadata={
                "engine": "mock",
                "output_length": len(bot_response),
                "redacted": len(pii_matches) > 0
            }
        )
    
    async def evaluate_tool_call(
        self, 
        tool_name: str, 
        tool_args: Dict[str, Any],
        user: User
    ) -> GuardrailsResult:
        """Mock tool call evaluation."""
        violations = []
        
        # Check tool permissions based on user role
        from app.security import rbac_manager
        
        if not rbac_manager.check_tool_access(user, tool_name):
            violations.append(GuardrailsViolation(
                violation_type=ViolationType.UNAUTHORIZED_TOOL,
                severity="high",
                message=f"Unauthorized tool access: {tool_name}",
                context={"tool": tool_name, "user_role": user.role.value},
                user_id=user.user_id,
                blocked=True,
                recommendation=f"Tool '{tool_name}' requires {', '.join(['admin']) if tool_name in ['get_user_profile', 'query_database'] else 'appropriate'} privileges."
            ))
        
        # Check for injection attempts in tool arguments
        for arg_name, arg_value in tool_args.items():
            if isinstance(arg_value, str):
                # Check for SQL injection patterns
                sql_injection_patterns = ["';", "UNION", "DROP", "DELETE"]
                for pattern in sql_injection_patterns:
                    if pattern.upper() in arg_value.upper():
                        violations.append(GuardrailsViolation(
                            violation_type=ViolationType.TOOL_INJECTION,
                            severity="critical",
                            message=f"Potential SQL injection in {arg_name}",
                            context={"arg": arg_name, "pattern": pattern},
                            user_id=user.user_id,
                            blocked=True,
                            recommendation="Please remove potentially harmful SQL patterns."
                        ))
                        break
                
                # Check for command injection patterns
                cmd_injection_patterns = [";", "&&", "|", "$("]
                for pattern in cmd_injection_patterns:
                    if pattern in arg_value:
                        violations.append(GuardrailsViolation(
                            violation_type=ViolationType.TOOL_INJECTION,
                            severity="critical",
                            message=f"Potential command injection in {arg_name}",
                            context={"arg": arg_name, "pattern": pattern},
                            user_id=user.user_id,
                            blocked=True,
                            recommendation="Please remove potentially harmful command patterns."
                        ))
                        break
        
        # Determine if tool call should be allowed
        critical_violations = [v for v in violations if v.severity == "critical"]
        high_violations = [v for v in violations if v.severity == "high"]
        
        allowed = len(critical_violations) == 0 and len(high_violations) == 0
        
        return GuardrailsResult(
            allowed=allowed,
            violations=violations,
            metadata={
                "engine": "mock",
                "tool": tool_name,
                "user_role": user.role.value
            }
        )


class NeMoGuardrailsEngine:
    """Production NeMo Guardrails engine integration."""
    
    def __init__(self, config_path: str):
        self.logger = get_logger("nemo_guardrails")
        self.config_path = config_path
        self.settings = get_settings()
        
        try:
            # Load NeMo Guardrails configuration
            self.config = RailsConfig.from_path(config_path)
            self.rails = LLMRails(self.config)
            
            self.logger.info(
                "NeMo Guardrails engine initialized",
                config_path=config_path
            )
            
        except Exception as e:
            self.logger.error(f"Failed to initialize NeMo Guardrails: {str(e)}")
            raise
    
    async def evaluate_input(
        self, 
        user_message: str, 
        user: User,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardrailsResult:
        """Evaluate input using NeMo Guardrails."""
        try:
            # Set user context for rails
            user_context = {
                "user_id": user.user_id,
                "role": user.role.value,
                "department": user.department
            }
            
            # Run input through NeMo Guardrails
            result = await self.rails.generate_async(
                messages=[{"role": "user", "content": user_message}],
                context=user_context
            )
            
            # Process NeMo result
            violations = self._extract_violations_from_nemo_result(result, user)
            
            # Determine if input is allowed
            allowed = not any(v.blocked for v in violations)
            
            return GuardrailsResult(
                allowed=allowed,
                violations=violations,
                metadata={
                    "engine": "nemo",
                    "input_length": len(user_message),
                    "nemo_result": result.get("metadata", {})
                }
            )
            
        except Exception as e:
            self.logger.error(f"NeMo input evaluation failed: {str(e)}")
            # Fallback to deny on error
            return GuardrailsResult(
                allowed=False,
                violations=[GuardrailsViolation(
                    violation_type=ViolationType.PROMPT_INJECTION,
                    severity="critical",
                    message="Guardrails evaluation failed",
                    context={"error": str(e)},
                    user_id=user.user_id,
                    blocked=True,
                    recommendation="Please try again or contact support."
                )],
                metadata={"engine": "nemo", "error": str(e)}
            )
    
    async def evaluate_output(
        self, 
        bot_response: str, 
        user: User,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardrailsResult:
        """Evaluate output using NeMo Guardrails."""
        try:
            # Run output through NeMo Guardrails output rails
            user_context = {
                "user_id": user.user_id,
                "role": user.role.value,
                "department": user.department
            }
            
            # Simulate full conversation for context
            messages = [
                {"role": "user", "content": context.get("user_message", "")},
                {"role": "assistant", "content": bot_response}
            ]
            
            result = await self.rails.generate_async(
                messages=messages,
                context=user_context
            )
            
            violations = self._extract_violations_from_nemo_result(result, user)
            modified_content = result.get("content") if result.get("content") != bot_response else None
            
            allowed = not any(v.blocked for v in violations)
            
            return GuardrailsResult(
                allowed=allowed,
                violations=violations,
                modified_content=modified_content,
                metadata={
                    "engine": "nemo",
                    "output_length": len(bot_response),
                    "nemo_result": result.get("metadata", {})
                }
            )
            
        except Exception as e:
            self.logger.error(f"NeMo output evaluation failed: {str(e)}")
            # Fallback to basic PII redaction
            redacted_response, pii_matches = secure_data_handler.redactor.redact_text(
                bot_response, preserve_format=False
            )
            
            violations = []
            if pii_matches:
                violations.append(GuardrailsViolation(
                    violation_type=ViolationType.OUTPUT_PII,
                    severity="high",
                    message="PII redacted (fallback processing)",
                    context={"pii_count": len(pii_matches), "error": str(e)},
                    user_id=user.user_id,
                    blocked=False
                ))
            
            return GuardrailsResult(
                allowed=True,
                violations=violations,
                modified_content=redacted_response if pii_matches else None,
                metadata={"engine": "nemo_fallback", "error": str(e)}
            )
    
    def _extract_violations_from_nemo_result(
        self, 
        nemo_result: Dict[str, Any], 
        user: User
    ) -> List[GuardrailsViolation]:
        """Extract violations from NeMo Guardrails result."""
        violations = []
        
        # Extract violations from NeMo metadata
        metadata = nemo_result.get("metadata", {})
        rail_violations = metadata.get("violations", [])
        
        for violation in rail_violations:
            try:
                # Handle case where violation is already a GuardrailsViolation object
                if isinstance(violation, GuardrailsViolation):
                    violations.append(violation)
                    continue
                
                # Normal case: violation is a dict from NeMo
                violation_type = self._map_nemo_violation_type(violation.get("type", "unknown"))
                
                violations.append(GuardrailsViolation(
                    violation_type=violation_type,
                    severity=violation.get("severity", "medium"),
                    message=violation.get("message", "Guardrails violation detected"),
                    context=violation.get("context", {}),
                    user_id=user.user_id,
                    blocked=violation.get("blocked", True),
                    recommendation=violation.get("recommendation")
                ))
            except AttributeError as e:
                self.logger.error(f"Error processing violation: {str(e)}, violation type: {type(violation)}")
                # Create a generic violation as fallback
                violations.append(GuardrailsViolation(
                    violation_type=ViolationType.PROMPT_INJECTION,
                    severity="medium",
                    message="Error processing violation",
                    context={"error": str(e)},
                    user_id=user.user_id,
                    blocked=True,
                    recommendation="Please try again"
                ))
        
        return violations
    
    def _map_nemo_violation_type(self, nemo_type: str) -> ViolationType:
        """Map NeMo violation types to internal enum."""
        mapping = {
            "prompt_injection": ViolationType.PROMPT_INJECTION,
            "jailbreak": ViolationType.JAILBREAK_ATTEMPT,
            "pii": ViolationType.PII_DETECTED,
            "unauthorized_tool": ViolationType.UNAUTHORIZED_TOOL,
            "restricted_topic": ViolationType.RESTRICTED_TOPIC,
            "output_pii": ViolationType.OUTPUT_PII,
            "information_leak": ViolationType.INFORMATION_LEAKAGE,
            "tool_injection": ViolationType.TOOL_INJECTION
        }
        
        return mapping.get(nemo_type, ViolationType.PROMPT_INJECTION)


class GuardrailsEngine:
    """Main guardrails engine that manages the appropriate backend."""
    
    def __init__(self):
        self.logger = get_logger("guardrails_engine")
        self.settings = get_settings()
        
        # Initialize appropriate engine based on availability
        if NEMO_AVAILABLE and os.path.exists(self.settings.guardrails.config_path):
            try:
                self.engine = NeMoGuardrailsEngine(self.settings.guardrails.config_path)
                self.engine_type = "nemo"
                self.logger.info("Using NeMo Guardrails engine")
            except Exception as e:
                self.logger.warning(f"NeMo Guardrails unavailable, using mock: {str(e)}")
                self.engine = MockGuardrailsEngine(self.settings.guardrails.config_path)
                self.engine_type = "mock"
        else:
            self.engine = MockGuardrailsEngine(self.settings.guardrails.config_path)
            self.engine_type = "mock"
            self.logger.info("Using mock guardrails engine")
    
    @trace_operation("guardrails_evaluate_input")
    async def evaluate_input(
        self, 
        user_message: str, 
        user: User,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardrailsResult:
        """Evaluate user input against guardrails."""
        result = await self.engine.evaluate_input(user_message, user, context)
        
        # Log violations
        for violation in result.violations:
            guardrails_logger.log_violation(
                violation_type=violation.violation_type.value,
                message=violation.message,
                blocked=violation.blocked,
                details={
                    "user_id": user.user_id,
                    "severity": violation.severity,
                    "context": violation.context
                }
            )
        
        # Log overall decision
        guardrails_logger.log_decision(
            decision="allow" if result.allowed else "block",
            reasoning=f"Input evaluation: {len(result.violations)} violations detected",
            input_safe=result.allowed
        )
        
        return result
    
    @trace_operation("guardrails_evaluate_output")
    async def evaluate_output(
        self, 
        bot_response: str, 
        user: User,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardrailsResult:
        """Evaluate bot output against guardrails."""
        result = await self.engine.evaluate_output(bot_response, user, context)
        
        # Log violations
        for violation in result.violations:
            guardrails_logger.log_violation(
                violation_type=violation.violation_type.value,
                message=violation.message,
                blocked=violation.blocked,
                details={
                    "user_id": user.user_id,
                    "severity": violation.severity,
                    "context": violation.context
                }
            )
        
        # Log overall decision
        guardrails_logger.log_decision(
            decision="allow" if result.allowed else "block",
            reasoning=f"Output evaluation: {len(result.violations)} violations detected",
            output_safe=result.allowed
        )
        
        return result
    
    @trace_operation("guardrails_evaluate_tool")
    async def evaluate_tool_call(
        self, 
        tool_name: str, 
        tool_args: Dict[str, Any],
        user: User
    ) -> GuardrailsResult:
        """Evaluate tool call against guardrails."""
        if hasattr(self.engine, 'evaluate_tool_call'):
            result = await self.engine.evaluate_tool_call(tool_name, tool_args, user)
        else:
            # Fallback for engines without tool evaluation
            result = GuardrailsResult(
                allowed=True,
                violations=[],
                metadata={"engine": self.engine_type, "fallback": True}
            )
        
        # Log violations
        for violation in result.violations:
            guardrails_logger.log_violation(
                violation_type=violation.violation_type.value,
                message=violation.message,
                blocked=violation.blocked,
                details={
                    "user_id": user.user_id,
                    "tool_name": tool_name,
                    "severity": violation.severity,
                    "context": violation.context
                }
            )
        
        return result
    
    def is_enabled(self, user: Optional[User] = None) -> bool:
        """Check if guardrails are enabled."""
        return self.settings.guardrails.enable_by_default
    
    def get_engine_info(self) -> Dict[str, Any]:
        """Get information about the current engine."""
        return {
            "type": self.engine_type,
            "available": NEMO_AVAILABLE,
            "config_path": self.settings.guardrails.config_path,
            "enabled_by_default": self.settings.guardrails.enable_by_default
        }


# Global guardrails engine instance
guardrails_engine = GuardrailsEngine()