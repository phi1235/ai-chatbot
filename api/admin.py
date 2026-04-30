"""Compatibility shim for admin router.

Refactor note:
- Route implementations now live under `api.admin.routes.*`
- Keep this module so existing imports like `import api.admin as admin_mod`
  and `from api.admin import router` continue to work during the modular-
  monolith route-split phase.
"""
from __future__ import annotations

from api.admin import router

__all__ = ["router"]
