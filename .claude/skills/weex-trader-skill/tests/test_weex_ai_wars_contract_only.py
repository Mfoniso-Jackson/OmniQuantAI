#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
SCRIPTS = ROOT / "scripts"


class AiWarsContractOnlyTests(unittest.TestCase):
    maxDiff = None

    def run_contract_help(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.setdefault("WEEX_SKIP_DEFAULT_DISCOVERY_SELFTEST", "1")
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "weex_contract_api.py"), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_skill_script(self, script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.setdefault("WEEX_SKIP_DEFAULT_DISCOVERY_SELFTEST", "1")
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script_name), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_spot_files_are_not_shipped_in_ai_wars_trader_skill(self) -> None:
        forbidden_paths = [
            "scripts/weex_spot_api.py",
            "references/spot-api-definitions.json",
            "references/spot-api-definitions.md",
            "references/spot-endpoints.md",
        ]

        shipped = [path for path in forbidden_paths if (ROOT / path).exists()]

        self.assertEqual(shipped, [])

    def test_contract_definitions_exclude_simulated_futures_endpoints(self) -> None:
        definitions = json.loads(
            (ROOT / "references" / "contract-api-definitions.json").read_text(encoding="utf-8")
        )["definitions"]

        simulated = [
            definition["key"]
            for definition in definitions
            if definition["key"].startswith("sim.") or "/sim/" in definition.get("path", "")
        ]

        self.assertEqual(simulated, [])

    def test_contract_definitions_publish_machine_readable_request_and_response_contracts(self) -> None:
        definitions = json.loads(
            (ROOT / "references" / "contract-api-definitions.json").read_text(encoding="utf-8")
        )["definitions"]

        self.assertEqual(len(definitions), 43)
        for definition in definitions:
            with self.subTest(key=definition["key"]):
                self.assertIn(definition["request_transport"], {"query", "body"})
                self.assertEqual(
                    definition["query_fields"] + definition["body_fields"],
                    [item["name"] for item in definition["request_params"]],
                )
                self.assertIn(
                    definition["response_container"],
                    {"object", "array", "conditional_object_or_array", "string"},
                )
                if definition["requires_auth"]:
                    self.assertIn(definition["permission"], {"USER_DATA", "TRADE"})

    def test_contract_order_definitions_match_current_real_trading_limits(self) -> None:
        definitions = json.loads(
            (ROOT / "references" / "contract-api-definitions.json").read_text(encoding="utf-8")
        )["definitions"]
        by_key = {definition["key"]: definition for definition in definitions}

        place_order = by_key["transaction.place_order"]
        time_in_force = next(
            item for item in place_order["request_params"] if item["name"] == "timeInForce"
        )
        self.assertIn("POST_ONLY", time_in_force["description"])

        batch = by_key["transaction.place_orders_batch"]
        batch_orders = next(
            item for item in batch["request_params"] if item["name"] == "batchOrders"
        )
        self.assertIn("Up to 5 orders", batch_orders["description"])
        self.assertEqual(batch["body_fields"], ["batchOrders"])
        self.assertEqual(batch["response_container"], "array")

    def test_manifest_and_file_index_do_not_route_spot_or_demo(self) -> None:
        manifest_text = (ROOT / "manifest.json").read_text(encoding="utf-8").lower()
        file_index_text = (ROOT / "file-index.json").read_text(encoding="utf-8").lower()
        combined = f"{manifest_text}\n{file_index_text}"

        forbidden_fragments = [
            "weex_spot_api.py",
            "spot-api-definitions",
            "spot-endpoints",
            '"spot"',
            "sim.",
            "--trading-mode",
            "--confirm-demo",
            "simulated futures",
            "demo is supported",
        ]
        offenders = [fragment for fragment in forbidden_fragments if fragment in combined]

        self.assertEqual(offenders, [])

    def test_production_files_do_not_ship_forbidden_market_or_environment_paths(self) -> None:
        forbidden = re.compile(
            r"(--confirm-demo|--trading-mode|\bsim\.|weex_spot_api|spot-api|spot-endpoints|"
            r"\bspot\b|现货|模拟盘|demo trading|demo futures)",
            re.IGNORECASE,
        )
        scanned_paths = (
            REPO_ROOT / "README.md",
            REPO_ROOT / "README.zh-CN.md",
            REPO_ROOT / "AGENTS.md",
            REPO_ROOT / "CLAUDE.md",
            REPO_ROOT / ".github" / "copilot-instructions.md",
            ROOT / "SKILL.md",
            ROOT / "README.md",
            ROOT / "manifest.json",
            ROOT / "file-index.json",
            ROOT / "scripts",
            ROOT / "references",
        )
        offenders: list[str] = []
        for path in scanned_paths:
            candidates = [path] if path.is_file() else sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
            for candidate in candidates:
                if "__pycache__" in candidate.parts or candidate.suffix in {".pyc", ".pyo"}:
                    continue
                text = candidate.read_text(encoding="utf-8", errors="ignore")
                if forbidden.search(text):
                    offenders.append(candidate.relative_to(REPO_ROOT).as_posix())

        self.assertEqual(offenders, [])

    def test_contract_cli_help_does_not_advertise_demo_mode(self) -> None:
        for args in (("--help",), ("call", "--help"), ("place-order", "--help")):
            completed = self.run_contract_help(*args)
            combined = f"{completed.stdout}\n{completed.stderr}"

            self.assertEqual(completed.returncode, 0, combined)
            self.assertNotIn("--confirm-demo", completed.stdout)
            self.assertNotIn("demo", completed.stdout.lower())
            self.assertNotIn("simulated futures", completed.stdout.lower())
            self.assertNotIn("sim.", completed.stdout.lower())

    def test_aggregator_cli_is_contract_only(self) -> None:
        for args in (("--help",), ("collect-replay", "--help"), ("collect-order-risk", "--help"), ("collect-account-risk", "--help")):
            completed = self.run_skill_script("weex_trade_data_aggregator.py", *args)
            combined = f"{completed.stdout}\n{completed.stderr}"

            self.assertEqual(completed.returncode, 0, combined)
            self.assertNotIn("spot", completed.stdout.lower())
            self.assertNotIn("demo", completed.stdout.lower())
            self.assertNotIn("--trading-mode", completed.stdout)

        rejected = self.run_skill_script("weex_trade_data_aggregator.py", "collect-account-risk", "--profile", "main", "--market", "spot")
        self.assertNotEqual(rejected.returncode, 0)

    def test_trade_guard_cli_is_contract_only(self) -> None:
        for args in (("--help",), ("preview-order", "--help"), ("confirm-order", "--help"), ("account-scan", "--help")):
            completed = self.run_skill_script("weex_trade_guard.py", *args)
            combined = f"{completed.stdout}\n{completed.stderr}"

            self.assertEqual(completed.returncode, 0, combined)
            self.assertNotIn("spot", completed.stdout.lower())
            self.assertNotIn("demo", completed.stdout.lower())
            self.assertNotIn("--confirm-demo", completed.stdout)
            self.assertNotIn("--trading-mode", completed.stdout)

        rejected = self.run_skill_script("weex_trade_guard.py", "account-scan", "--profile", "main", "--market", "spot")
        self.assertNotEqual(rejected.returncode, 0)


if __name__ == "__main__":
    unittest.main()
