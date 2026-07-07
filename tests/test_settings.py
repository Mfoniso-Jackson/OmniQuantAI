from __future__ import annotations

import os
import unittest

from omniquantai.configuration.settings import assert_live_trading_permitted, load_settings


class SettingsTests(unittest.TestCase):
    def test_live_trading_requires_two_confirmations(self) -> None:
        old_enable = os.environ.pop("ENABLE_LIVE_TRADING", None)
        old_confirm = os.environ.pop("CONFIRM_REAL_MONEY", None)
        try:
            settings = load_settings()
            self.assertFalse(settings.live_trading_allowed)
            with self.assertRaises(PermissionError):
                assert_live_trading_permitted(settings)
        finally:
            if old_enable is not None:
                os.environ["ENABLE_LIVE_TRADING"] = old_enable
            if old_confirm is not None:
                os.environ["CONFIRM_REAL_MONEY"] = old_confirm

