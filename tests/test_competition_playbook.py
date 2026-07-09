from __future__ import annotations

from decimal import Decimal
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from omniquantai.application.competition import run_competition_playbook
from omniquantai.configuration.settings import TradingSettings


class CompetitionPlaybookTests(unittest.TestCase):
    def test_playbook_generates_evidence_without_live_trading(self) -> None:
        with TemporaryDirectory() as temp_dir:
            report = run_competition_playbook(Path(temp_dir), TradingSettings(initial_cash=Decimal("100000")))

            self.assertEqual(report.mode, "DRY_RUN")
            self.assertGreater(report.performance.trade_count, 0)
            self.assertTrue(Path(report.decision_log_path).exists())
            self.assertTrue(Path(report.ai_log_path).exists())
            self.assertIn(report.recommendation, {"STAY_IN_DRY_RUN", "READY_FOR_PROFILE_AND_ACCOUNT_CHECKS"})

