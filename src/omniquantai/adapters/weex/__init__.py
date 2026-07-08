"""WEEX adapter namespace.

This namespace bridges the legacy root-level WEEX modules into the
institutional package layout. A later mechanical migration can move the
module files themselves once the adapter contract is stable.
"""

from weex.execution_engine import ExecutionConfig, ExecutionEngine
from weex.position_manager import PositionManager, PositionState

__all__ = ["ExecutionConfig", "ExecutionEngine", "PositionManager", "PositionState"]
