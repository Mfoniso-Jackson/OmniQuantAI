import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import capture_ai_log_upload_evidence  # noqa: E402


class CaptureAiLogUploadEvidenceTests(unittest.TestCase):
    def test_parse_ai_log_arg_requires_file_reference(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            capture_ai_log_upload_evidence.parse_ai_log_arg(
                '{"stage":"Strategy Generation","model":"gpt-5-2026-03-01","input":{"messages":[{"role":"user","content":"ping"}]},"output":{"symbol":"ETHUSDT","action":"BUY"},"explanation":"test"}'
            )
        self.assertIn("@file.json", str(exc.exception))

    def test_execute_capture_dry_run_preserves_chinese_explanation(self) -> None:
        ai_log = {
            "stage": "Strategy Generation",
            "model": "gpt-5-2026-03-01",
            "input": {"messages": [{"role": "user", "content": "ping"}]},
            "output": {"symbol": "ETHUSDT", "action": "BUY"},
            "explanation": "中文解释：ETHUSDT 触发后立即执行，验证链路。",
        }

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            "os.environ",
            {
                "WEEX_API_KEY": "key",
                "WEEX_API_SECRET": "secret",
                "WEEX_API_PASSPHRASE": "passphrase",
            },
            clear=False,
        ):
            summary = capture_ai_log_upload_evidence.execute_capture(
                ai_log_body=ai_log,
                base_url="https://stg-api-contract.weex.tech",
                locale_name="en-US",
                timeout=5.0,
                evidence_root=Path(tmpdir),
                label="乱码排查",
                confirm_live=False,
            )
            capture_path = Path(summary["files"]["capture"])
            preview_path = Path(summary["files"]["requestPreview"])
            source_path = Path(summary["files"]["sourceAiLog"])
            capture_payload = json.loads(capture_path.read_text(encoding="utf-8"))
            preview_payload = json.loads(preview_path.read_text(encoding="utf-8"))
            source_payload = json.loads(source_path.read_text(encoding="utf-8"))

            self.assertEqual(source_payload["explanation"], ai_log["explanation"])
            self.assertEqual(capture_payload["body"]["explanation"], ai_log["explanation"])
            self.assertIn(ai_log["explanation"], capture_payload["serializedBody"])
            self.assertEqual(preview_payload["explanationAnalysis"]["questionMarkCount"], 0)
            self.assertGreater(preview_payload["explanationAnalysis"]["nonAsciiCount"], 0)
            self.assertFalse(preview_payload["confirmLive"])

    def test_execute_capture_live_writes_response_file(self) -> None:
        ai_log = {
            "stage": "Strategy Generation",
            "model": "gpt-5-2026-03-01",
            "input": {"messages": [{"role": "user", "content": "ping"}]},
            "output": {"symbol": "ETHUSDT", "action": "BUY"},
            "explanation": "test explanation",
        }

        mocked_response = {"ok": True, "status": 200, "data": {"code": "0", "msg": "success", "data": {"id": 1}}}
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            "os.environ",
            {
                "WEEX_API_KEY": "key",
                "WEEX_API_SECRET": "secret",
                "WEEX_API_PASSPHRASE": "passphrase",
            },
            clear=False,
        ), mock.patch(
            "capture_ai_log_upload_evidence.weex_ai_api.WeexAiClient.send",
            return_value=mocked_response,
        ) as mocked_send:
            summary = capture_ai_log_upload_evidence.execute_capture(
                ai_log_body=ai_log,
                base_url="https://stg-api-contract.weex.tech",
                locale_name="en-US",
                timeout=5.0,
                evidence_root=Path(tmpdir),
                label="live-check",
                confirm_live=True,
            )
            response_path = Path(summary["files"]["response"])
            response_payload = json.loads(response_path.read_text(encoding="utf-8"))
            mocked_send.assert_called_once()
            self.assertTrue(summary["confirmLive"])
            self.assertTrue(response_payload["businessOk"])
            self.assertEqual(response_payload["exitCode"], 0)


if __name__ == "__main__":
    unittest.main()
