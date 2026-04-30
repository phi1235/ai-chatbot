from __future__ import annotations

from fastapi import APIRouter

from .routes.coverage_gaps import router as coverage_gaps_router
from .routes.eval_gates import router as eval_gates_router
from .routes.evals import router as evals_router
from .routes.feedback import router as feedback_router
from .routes.feedback_actions import router as feedback_actions_router
from .routes.freshness import router as freshness_router
from .routes.sources import router as sources_router

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(sources_router)
router.include_router(freshness_router)
router.include_router(feedback_router)
router.include_router(coverage_gaps_router)
router.include_router(feedback_actions_router)
router.include_router(evals_router)
router.include_router(eval_gates_router)
