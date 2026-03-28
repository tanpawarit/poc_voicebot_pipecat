import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class SessionRegistry:
    _sessions: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    _start_time: float = field(default_factory=time.time)

    def add(self, session_id: str, task: asyncio.Task[None]) -> None:
        self._sessions[session_id] = task

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def cancel_all(self) -> None:
        tasks = list(self._sessions.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sessions.clear()

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    def health_info(self) -> dict[str, object]:
        return {
            "status": "ok",
            "active_sessions": self.active_count,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }
