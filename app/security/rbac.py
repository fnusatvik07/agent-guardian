"""
Role-Based Access Control (RBAC) for enterprise AI agent.
Implements fine-grained permissions and tool access control.
"""
from typing import List, Dict, Set, Optional
from enum import Enum
from dataclasses import dataclass

from app.config import get_settings
from app.observability import get_logger


class Role(str, Enum):
    """User roles with hierarchical permissions."""
    EMPLOYEE = "employee"
    ADMIN = "admin"
    SYSTEM = "system"  # For internal operations


class Permission(str, Enum):
    """Fine-grained permissions for different operations."""
    # Tool permissions
    USE_SEARCH_TOOLS = "use_search_tools"
    USE_INTERNAL_KB = "use_internal_kb"
    CREATE_TICKETS = "create_tickets"
    ACCESS_USER_PROFILES = "access_user_profiles"
    QUERY_DATABASES = "query_databases"
    ACCESS_SENSITIVE_DOCS = "access_sensitive_docs"
    
    # Data permissions
    VIEW_PII = "view_pii"
    EXPORT_DATA = "export_data"
    
    # System permissions
    BYPASS_GUARDRAILS = "bypass_guardrails"
    ADMIN_FUNCTIONS = "admin_functions"


@dataclass
class User:
    """User representation with role and permissions."""
    user_id: str
    role: Role
    department: Optional[str] = None
    permissions: Optional[Set[Permission]] = None
    
    def __post_init__(self):
        if self.permissions is None:
            self.permissions = get_role_permissions(self.role)


# Role-to-permission mapping
ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.EMPLOYEE: {
        Permission.USE_SEARCH_TOOLS,
        Permission.USE_INTERNAL_KB,
        Permission.CREATE_TICKETS,
    },
    Role.ADMIN: {
        Permission.USE_SEARCH_TOOLS,
        Permission.USE_INTERNAL_KB,
        Permission.CREATE_TICKETS,
        Permission.ACCESS_USER_PROFILES,
        Permission.QUERY_DATABASES,
        Permission.ACCESS_SENSITIVE_DOCS,
        Permission.VIEW_PII,
        Permission.EXPORT_DATA,
        Permission.ADMIN_FUNCTIONS,
    },
    Role.SYSTEM: set(Permission),  # System has all permissions
}


def get_role_permissions(role: Role) -> Set[Permission]:
    """Get permissions for a given role."""
    return ROLE_PERMISSIONS.get(role, set())


class RBACManager:
    """Manages role-based access control and permissions."""
    
    def __init__(self):
        self.logger = get_logger("rbac")
        self.settings = get_settings()
    
    def create_user(self, user_id: str, role: str, department: Optional[str] = None) -> User:
        """Create a user with appropriate role and permissions."""
        try:
            user_role = Role(role)
        except ValueError:
            self.logger.warning(f"Invalid role provided: {role}, defaulting to employee")
            user_role = Role.EMPLOYEE
        
        user = User(
            user_id=user_id,
            role=user_role,
            department=department
        )
        
        self.logger.info(
            f"User created with role {user_role}",
            user_id=user_id,
            role=user_role.value,
            permissions=[p.value for p in user.permissions]
        )
        
        return user
    
    def check_permission(self, user: User, permission: Permission) -> bool:
        """Check if user has a specific permission."""
        has_permission = permission in user.permissions
        
        self.logger.debug(
            f"Permission check: {permission.value}",
            user_id=user.user_id,
            role=user.role.value,
            permission=permission.value,
            granted=has_permission
        )
        
        return has_permission
    
    def check_tool_access(self, user: User, tool_name: str) -> bool:
        """Check if user can access a specific tool."""
        # Get allowed tools from settings based on role
        if user.role == Role.ADMIN:
            allowed_tools = self.settings.security.admin_allowed_tools
        else:
            allowed_tools = self.settings.security.employee_allowed_tools
        
        has_access = tool_name in allowed_tools
        
        self.logger.info(
            f"Tool access check: {tool_name}",
            user_id=user.user_id,
            role=user.role.value,
            tool=tool_name,
            granted=has_access
        )
        
        if not has_access:
            self.logger.warning(
                f"Tool access denied: {tool_name}",
                user_id=user.user_id,
                role=user.role.value,
                tool=tool_name,
                event_type="access_denied"
            )
        
        return has_access
    
    def get_accessible_tools(self, user: User) -> List[str]:
        """Get list of tools accessible to the user."""
        if user.role == Role.ADMIN:
            return self.settings.security.admin_allowed_tools
        else:
            return self.settings.security.employee_allowed_tools
    
    def audit_access_attempt(
        self, 
        user: User, 
        resource: str, 
        action: str, 
        granted: bool,
        details: Optional[Dict] = None
    ):
        """Audit access attempts for security monitoring."""
        self.logger.info(
            f"Access audit: {action} on {resource}",
            user_id=user.user_id,
            role=user.role.value,
            resource=resource,
            action=action,
            granted=granted,
            details=details or {},
            event_type="access_audit"
        )


# Global RBAC manager instance
rbac_manager = RBACManager()


def require_permission(permission: Permission):
    """Decorator to require specific permission for function access."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # In a real implementation, you'd extract user from request context
            # For now, this is a placeholder for the pattern
            user = kwargs.get('user')
            if not user or not rbac_manager.check_permission(user, permission):
                raise PermissionError(f"Permission {permission.value} required")
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(required_role: Role):
    """Decorator to require specific role for function access."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            user = kwargs.get('user')
            if not user or user.role != required_role:
                raise PermissionError(f"Role {required_role.value} required")
            return func(*args, **kwargs)
        return wrapper
    return decorator