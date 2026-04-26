"""Session memory — wrapper qua SQLite store để persistent across restart.

Giữ API cũ (`add_turn`, `get_context`) để minimal-impact với agent.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from orchestrator import store


@dataclass(slots=True)
class SessionMemory:
    max_turns: int = 8

    def add_turn(self, session_id: str, role: str, content: str) -> None:
        # Chỉ ghi role + content (citations/trace được agent ghi riêng qua add_rich_message)
        store.add_message(session_id, role, content)

    def get_context(self, session_id: str) -> list[dict[str, str]]:
        return store.get_recent_turns(session_id, max_turns=self.max_turns)


session_memory = SessionMemory()
