#!/usr/bin/env python3
"""Compatibility entry point for the localized WEEX profile CLI."""

from __future__ import annotations

from weex_profile_language import resolve_language
from weex_profiles_cli import main


if __name__ == "__main__":
    raise SystemExit(main(resolve_language()))
