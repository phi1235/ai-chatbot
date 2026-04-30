"""Admin UI feature pages."""

from .coverage_gaps import page_coverage_gaps
from .dashboard import page_dashboard
from .eval_cases import page_eval_cases
from .eval_gates import page_eval_gates
from .feedback import page_feedback
from .feedback_actions import page_feedback_actions
from .freshness import page_freshness_center
from .health import page_health
from .maintenance import page_maintenance
from .sessions import page_sessions
from .sources import page_sources

__all__ = [
    "page_coverage_gaps",
    "page_dashboard",
    "page_eval_cases",
    "page_eval_gates",
    "page_feedback",
    "page_feedback_actions",
    "page_freshness_center",
    "page_health",
    "page_maintenance",
    "page_sessions",
    "page_sources",
]
