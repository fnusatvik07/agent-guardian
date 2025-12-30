"""
Advanced PII redaction and sensitive data protection.
Implements multiple detection strategies and context-aware redaction.
"""
import re
from typing import Dict, List, Any, Optional, Tuple, Pattern
from dataclasses import dataclass
from enum import Enum

from app.config import get_settings
from app.observability import get_logger


class PIIType(str, Enum):
    """Types of PII that can be detected and redacted."""
    SSN = "ssn"
    EMAIL = "email"
    PHONE = "phone"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    API_KEY = "api_key"
    PASSWORD = "password"
    ADDRESS = "address"
    NAME = "name"
    CUSTOM = "custom"


@dataclass
class PIIMatch:
    """Represents a detected PII match."""
    pii_type: PIIType
    value: str
    start: int
    end: int
    confidence: float = 1.0
    context: Optional[str] = None


class PIIDetector:
    """Advanced PII detection with multiple strategies."""
    
    def __init__(self):
        self.logger = get_logger("pii_detection")
        self.settings = get_settings()
        
        # Compile regex patterns for better performance
        self.patterns: Dict[PIIType, List[Pattern]] = {
            PIIType.SSN: [
                re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
                re.compile(r'\b\d{3}\s\d{2}\s\d{4}\b'),
                re.compile(r'\b\d{9}\b'),
            ],
            PIIType.EMAIL: [
                re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            ],
            PIIType.PHONE: [
                re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
                re.compile(r'\(\d{3}\)\s?\d{3}[-.]?\d{4}\b'),
                re.compile(r'\+1[-.]?\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
            ],
            PIIType.CREDIT_CARD: [
                re.compile(r'\b4[0-9]{12}(?:[0-9]{3})?\b'),  # Visa
                re.compile(r'\b5[1-5][0-9]{14}\b'),  # Mastercard
                re.compile(r'\b3[47][0-9]{13}\b'),  # American Express
            ],
            PIIType.IP_ADDRESS: [
                re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'),
            ],
            PIIType.API_KEY: [
                re.compile(r'\b[A-Za-z0-9]{32,}\b'),  # Generic long alphanumeric
                re.compile(r'sk-[A-Za-z0-9]{20,}'),  # OpenAI style
                re.compile(r'Bearer\s+[A-Za-z0-9._-]+'),  # Bearer tokens
            ],
            PIIType.PASSWORD: [
                re.compile(r'password[\s:=]+[^\s]+', re.IGNORECASE),
                re.compile(r'pwd[\s:=]+[^\s]+', re.IGNORECASE),
                re.compile(r'pass[\s:=]+[^\s]+', re.IGNORECASE),
            ],
        }
        
        # Context keywords that increase confidence
        self.context_keywords: Dict[PIIType, List[str]] = {
            PIIType.SSN: ['social', 'security', 'ssn', 'tax'],
            PIIType.EMAIL: ['email', 'contact', 'address'],
            PIIType.PHONE: ['phone', 'tel', 'call', 'mobile'],
            PIIType.CREDIT_CARD: ['card', 'credit', 'payment', 'billing'],
            PIIType.API_KEY: ['key', 'token', 'api', 'secret'],
            PIIType.PASSWORD: ['password', 'pwd', 'pass', 'auth'],
        }
    
    def detect_pii(self, text: str, context: Optional[str] = None) -> List[PIIMatch]:
        """Detect PII in text with context awareness."""
        matches = []
        
        for pii_type, patterns in self.patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    confidence = self._calculate_confidence(match.group(), pii_type, context)
                    
                    pii_match = PIIMatch(
                        pii_type=pii_type,
                        value=match.group(),
                        start=match.start(),
                        end=match.end(),
                        confidence=confidence,
                        context=context
                    )
                    matches.append(pii_match)
        
        # Sort by position for consistent redaction
        matches.sort(key=lambda x: x.start)
        
        self.logger.debug(
            f"PII detection completed: {len(matches)} matches found",
            text_length=len(text),
            matches_found=len(matches),
            types_detected=[m.pii_type.value for m in matches]
        )
        
        return matches
    
    def _calculate_confidence(self, value: str, pii_type: PIIType, context: Optional[str]) -> float:
        """Calculate confidence score based on context."""
        base_confidence = 0.8
        
        if context and pii_type in self.context_keywords:
            context_lower = context.lower()
            for keyword in self.context_keywords[pii_type]:
                if keyword in context_lower:
                    base_confidence += 0.15
                    break
        
        # Specific validations
        if pii_type == PIIType.SSN:
            # Basic SSN validation (not starting with 000, 666, or 9xx)
            cleaned = re.sub(r'[^0-9]', '', value)
            if cleaned.startswith(('000', '666')) or cleaned.startswith('9'):
                base_confidence *= 0.5
        
        return min(base_confidence, 1.0)


class DataRedactor:
    """Handles redaction of sensitive data with preservation of structure."""
    
    def __init__(self, detector: Optional[PIIDetector] = None):
        self.detector = detector or PIIDetector()
        self.logger = get_logger("data_redaction")
    
    def redact_text(
        self, 
        text: str, 
        redaction_char: str = "*",
        preserve_format: bool = True,
        context: Optional[str] = None
    ) -> Tuple[str, List[PIIMatch]]:
        """Redact PII from text while preserving structure."""
        matches = self.detector.detect_pii(text, context)
        
        if not matches:
            return text, []
        
        # Redact from end to start to preserve positions
        redacted_text = text
        redacted_matches = []
        
        for match in reversed(matches):
            if match.confidence >= 0.7:  # Only redact high-confidence matches
                if preserve_format:
                    # Preserve format (e.g., 123-45-6789 -> ***-**-****)
                    redacted_value = self._preserve_format_redaction(
                        match.value, redaction_char
                    )
                else:
                    redacted_value = f"[REDACTED_{match.pii_type.value.upper()}]"
                
                redacted_text = (
                    redacted_text[:match.start] + 
                    redacted_value + 
                    redacted_text[match.end:]
                )
                redacted_matches.append(match)
        
        self.logger.info(
            f"Text redaction completed",
            original_length=len(text),
            redacted_length=len(redacted_text),
            pii_instances_redacted=len(redacted_matches),
            types_redacted=[m.pii_type.value for m in redacted_matches]
        )
        
        return redacted_text, redacted_matches
    
    def redact_dict(
        self, 
        data: Dict[str, Any], 
        redaction_char: str = "*",
        preserve_format: bool = True
    ) -> Tuple[Dict[str, Any], List[PIIMatch]]:
        """Recursively redact PII from dictionary data."""
        all_matches = []
        redacted_data = {}
        
        for key, value in data.items():
            if isinstance(value, str):
                redacted_value, matches = self.redact_text(
                    value, redaction_char, preserve_format, context=key
                )
                redacted_data[key] = redacted_value
                all_matches.extend(matches)
            elif isinstance(value, dict):
                redacted_value, matches = self.redact_dict(
                    value, redaction_char, preserve_format
                )
                redacted_data[key] = redacted_value
                all_matches.extend(matches)
            elif isinstance(value, list):
                redacted_list = []
                for item in value:
                    if isinstance(item, str):
                        redacted_item, matches = self.redact_text(
                            item, redaction_char, preserve_format, context=key
                        )
                        redacted_list.append(redacted_item)
                        all_matches.extend(matches)
                    elif isinstance(item, dict):
                        redacted_item, matches = self.redact_dict(
                            item, redaction_char, preserve_format
                        )
                        redacted_list.append(redacted_item)
                        all_matches.extend(matches)
                    else:
                        redacted_list.append(item)
                redacted_data[key] = redacted_list
            else:
                redacted_data[key] = value
        
        return redacted_data, all_matches
    
    def _preserve_format_redaction(self, value: str, redaction_char: str) -> str:
        """Redact while preserving the original format structure."""
        result = ""
        for char in value:
            if char.isalnum():
                result += redaction_char
            else:
                result += char
        return result


class SecureDataHandler:
    """High-level interface for secure data handling."""
    
    def __init__(self):
        self.detector = PIIDetector()
        self.redactor = DataRedactor(self.detector)
        self.logger = get_logger("secure_data")
    
    def sanitize_for_logging(self, data: Any) -> Any:
        """Sanitize data for safe logging."""
        if isinstance(data, str):
            sanitized, matches = self.redactor.redact_text(data, preserve_format=False)
            if matches:
                self.logger.debug(f"Sanitized {len(matches)} PII instances for logging")
            return sanitized
        elif isinstance(data, dict):
            sanitized, matches = self.redactor.redact_dict(data, preserve_format=False)
            if matches:
                self.logger.debug(f"Sanitized {len(matches)} PII instances from dict")
            return sanitized
        else:
            return data
    
    def validate_input_safety(self, user_input: str) -> Tuple[bool, List[PIIMatch]]:
        """Validate if user input contains PII that should be blocked."""
        matches = self.detector.detect_pii(user_input)
        
        # Filter for high-confidence, sensitive PII types
        sensitive_matches = [
            match for match in matches
            if match.confidence >= 0.8 and match.pii_type in [
                PIIType.SSN, PIIType.CREDIT_CARD, PIIType.API_KEY, PIIType.PASSWORD
            ]
        ]
        
        is_safe = len(sensitive_matches) == 0
        
        if not is_safe:
            self.logger.warning(
                "Potentially unsafe input detected",
                sensitive_pii_count=len(sensitive_matches),
                types=[m.pii_type.value for m in sensitive_matches]
            )
        
        return is_safe, sensitive_matches


# Global instances
pii_detector = PIIDetector()
data_redactor = DataRedactor(pii_detector)
secure_data_handler = SecureDataHandler()