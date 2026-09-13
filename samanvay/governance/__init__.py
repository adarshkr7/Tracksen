"""Governance: who may approve a block plan, and an audit trail that cannot be rewritten."""

from .accounts import (
    Account,
    AccountStore,
    AuthenticationError,
    PasswordPolicyError,
    bootstrap,
    check_password_policy,
    load_or_bootstrap,
    new_account,
)
from .audit import Action, AuditEntry, AuditLog, ChainStatus
from .identity import AuthService, LoginResult
from .planstore import PlanStore, PlanStoreError, StoredPlan
from .sessions import Session, SessionStore, hash_token
from .workflow import (
    CONCURRENCE_AUTHORITY,
    DEPARTMENT_HEAD,
    Actor,
    ApprovalWorkflow,
    AuthorityError,
    Concurrence,
    PlanApproval,
    PlanState,
    Role,
    WorkflowError,
)

__all__ = [
    "Action", "Actor", "ApprovalWorkflow", "AuditEntry", "AuditLog", "AuthorityError",
    "CONCURRENCE_AUTHORITY", "ChainStatus", "Concurrence", "DEPARTMENT_HEAD",
    "PlanApproval", "PlanState", "Role", "WorkflowError",
    # Authentication: accounts prove who you are, sessions carry it, AuthService joins them
    "Account", "AccountStore", "AuthService", "AuthenticationError", "LoginResult",
    "PasswordPolicyError", "Session", "SessionStore",
    "bootstrap", "check_password_policy", "hash_token", "load_or_bootstrap",
    "new_account",
    "PlanStore", "PlanStoreError", "StoredPlan",
]
