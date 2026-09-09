"""Process-local registry for evidence issued by the trusted reconciliation boundary."""

from __future__ import annotations

from threading import RLock
from weakref import WeakKeyDictionary
from typing import Any


_LOCK = RLock()
_ISSUED_EVIDENCE: WeakKeyDictionary[Any, bool] = WeakKeyDictionary()


def register_issued_evidence(value: Any) -> None:
    """Remember an evidence object by identity until it is garbage-collected."""
    try:
        with _LOCK:
            _ISSUED_EVIDENCE[value] = True
    except TypeError as exc:
        raise ValueError("UNTRUSTED_USAGE_EVIDENCE") from exc


def is_issued_evidence(value: Any) -> bool:
    """Return whether this exact object was issued by a trusted builder."""
    try:
        with _LOCK:
            # WeakKeyDictionary membership can consult user-defined equality.
            # Compare identities explicitly so a forged object cannot collide
            # with an issued key through a matching hash or __eq__ method.
            return any(candidate is value for candidate in _ISSUED_EVIDENCE)
    except TypeError:
        return False


__all__ = ["is_issued_evidence", "register_issued_evidence"]
