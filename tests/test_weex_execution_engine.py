from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from omniquantai.adapters.weex import ExecutionConfig, ExecutionEngine, PositionManager


class FakeClient:
    def __init__(self) -> None:
        self.orders: list[dict[str, object]] = []
        self.positions: object = None

    def get_single_position(self, symbol: str) -> object:
        return self.positions

    def place_order(self, payload: dict[str, object]) -> dict[str, object]:
        self.orders.append(payload)
        return {"order_id": "12345"}

    def private_post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        return {"code": "00000", "path": path, "payload": payload}


class WeexExecutionEngineTests(unittest.TestCase):
    def _engine(self, cfg: ExecutionConfig) -> tuple[ExecutionEngine, FakeClient]:
        client = FakeClient()
        state_file = Path(tempfile.mkdtemp()) / "position_state.json"
        manager = PositionManager(client=client, symbol=cfg.symbol, state_file=str(state_file))
        return ExecutionEngine(client=client, pm=manager, cfg=cfg), client

    def test_dry_run_open_does_not_place_order(self) -> None:
        engine, client = self._engine(ExecutionConfig(dry_run=True, min_confidence=0.2))

        result = engine.manage(
            router={"regime": "TRENDING"},
            decision={"decision": "BUY", "confidence": 0.9},
            ticker={"last": "100"},
            model_name="test-model",
        )

        self.assertEqual(result["action"], "DRY_RUN_OPEN")
        self.assertEqual(client.orders, [])

    def test_low_confidence_entry_is_blocked(self) -> None:
        engine, client = self._engine(ExecutionConfig(dry_run=False, min_confidence=0.5))

        result = engine.manage(
            router={"regime": "TRENDING"},
            decision={"decision": "BUY", "confidence": 0.1},
            ticker={"last": "100"},
            model_name="test-model",
        )

        self.assertEqual(result["action"], "BLOCKED")
        self.assertEqual(result["reason"], "confidence_below_minimum")
        self.assertEqual(client.orders, [])

    def test_short_entry_can_be_disabled(self) -> None:
        engine, client = self._engine(ExecutionConfig(dry_run=False, allow_short=False))

        result = engine.manage(
            router={"regime": "TRENDING"},
            decision={"decision": "SELL", "confidence": 0.9},
            ticker={"last": "100"},
            model_name="test-model",
        )

        self.assertEqual(result["action"], "BLOCKED")
        self.assertEqual(result["reason"], "short_entries_disabled")
        self.assertEqual(client.orders, [])

