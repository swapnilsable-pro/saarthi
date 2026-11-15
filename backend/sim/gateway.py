"""Order gateway seam.

SimulatedExchange is, and must remain, the ONLY implementation. There is deliberately no
live gateway class; tests/test_no_broker.py fails if one appears.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OrderGateway(ABC):
    paper: bool = True

    @abstractmethod
    def place(self, order: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def cancel(self, order_id: str) -> dict[str, Any]: ...

# The one implementation lives in backend/sim/paper.py (SimulatedExchange).
