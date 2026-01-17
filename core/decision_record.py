"""
OmniQuantAI - Decision Record
----------------------------
Canonical, immutable representation of an AI trading decision.

Purpose:
- Standardize decision output across engines
- Enable auditability & replay
- Serve as the transparency + coordination layer
- Future anchoring to Sui (hash → on-chain)

This file MUST NOT contain strategy logic.
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict
from datetime import datetime
import hashlib
import json


# ===============================
# Decision Record Schema
# ===============================

@dataclass(frozen=True)
class DecisionRecord:
    # Identity
    decision_id: str
    timestamp: str

    # Market context
    symbol: str
    timeframe: str
    price: float

    # AI output
    decision: str          # BUY / SELL / HOLD
    confidence: float      # 0.0 → 1.0

    # Risk output
    position_size: Optional[float] = None
    approved: Optional[bool] = None
    rejection_reason: Optional[str] = None

    # Explainability
    signals: Optional[Dict[str, float]] = None
    model_version: Optional[str] = None

    # Integrity
    decision_hash: Optional[str] = None


# ===============================
# Factory
# ===============================

def create_decision_record(
    symbol: str,
    timeframe: str,
    price: float,
    decision: str,
    confidence: float,
    signals: Optional[Dict[str, float]] = None,
    model_version: str = "v1.0"
) -> DecisionRecord:
    """
    Create a new decision record before risk evaluation.
    """

    timestamp = datetime.utcnow().isoformat()
    raw_id = f"{symbol}:{timeframe}:{timestamp}"
    decision_id = hashlib.sha256(raw_id.encode()).hexdigest()

    record = DecisionRecord(
        decision_id=decision_id,
        timestamp=timestamp,
        symbol=symbol,
        timeframe=timeframe,
        price=price,
        decision=decision,
        confidence=round(confidence, 4),
        signals=signals,
        model_version=model_version
    )

    return attach_hash(record)


# ===============================
# Risk Attachment
# ===============================

def attach_risk_outcome(
    record: DecisionRecord,
    approved: bool,
    position_size: Optional[float] = None,
    rejection_reason: Optional[str] = None
) -> DecisionRecord:
    """
    Attach risk engine outcome to decision.
    """

    updated = DecisionRecord(
        **{
            **asdict(record),
            "approved": approved,
            "position_size": position_size,
            "rejection_reason": rejection_reason
        }
    )

    return attach_hash(updated)


# ===============================
# Hashing (Integrity Layer)
# ===============================

def attach_hash(record: DecisionRecord) -> DecisionRecord:
    """
    Create deterministic hash of the decision record.
    """

    record_dict = asdict(record)
    record_dict["decision_hash"] = None  # exclude hash from hash

    serialized = json.dumps(record_dict, sort_keys=True)
    decision_hash = hashlib.sha256(serialized.encode()).hexdigest()

    return DecisionRecord(
        **{
            **record_dict,
            "decision_hash": decision_hash
        }
    )


# ===============================
# Serialization
# ===============================

def to_dict(record: DecisionRecord) -> Dict:
    return asdict(record)


def to_json(record: DecisionRecord) -> str:
    return json.dumps(asdict(record), indent=2)


# ===============================
# Example Usage
# ===============================

if __name__ == "__main__":
    record = create_decision_record(
        symbol="BTCUSDT",
        timeframe="1m",
        price=43125.5,
        decision="BUY",
        confidence=0.62,
        signals={
            "momentum": 0.71,
            "trend": 0.55,
            "volatility": 0.33
        }
    )

    record = attach_risk_outcome(
        record,
        approved=True,
        position_size=120.0
    )

    print("OmniQuantAI Decision Record")
    print("-" * 40)
    print(to_json(record))
