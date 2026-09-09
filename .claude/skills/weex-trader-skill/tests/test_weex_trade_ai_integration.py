import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import weex_ai_api  # noqa: E402
import weex_contract_api  # noqa: E402


class WeexTradeAiIntegrationTests(unittest.TestCase):
    def test_validate_ai_log_payload_rejects_documentation_placeholder_model_identifier(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            weex_ai_api.validate_ai_log_payload(
                {
                    "stage": "Strategy Generation",
                    "model": "provider-returned-model-id",
                    "input": {"messages": [{"role": "user", "content": "ping"}]},
                    "output": {},
                    "explanation": "x",
                },
                "AI log body",
            )
        self.assertIn("documentation placeholder", str(exc.exception))

    def test_validate_ai_log_payload_preserves_exact_model_identifier(self) -> None:
        payload = {
            "stage": "Strategy Generation",
            "model": "gpt-5-2026-03-01",
            "input": {"messages": [{"role": "user", "content": "ping"}]},
            "output": {},
            "explanation": "x",
        }
        validated = weex_ai_api.validate_ai_log_payload(payload, "AI log body")
        self.assertEqual(validated["model"], "gpt-5-2026-03-01")

        with self.assertRaises(SystemExit) as exc:
            weex_ai_api.validate_ai_log_payload(
                {
                    "stage": "Strategy Generation",
                    "model": " gpt-5-2026-03-01 ",
                    "input": {"messages": [{"role": "user", "content": "ping"}]},
                    "output": {},
                    "explanation": "x",
                },
                "AI log body",
            )
        self.assertIn("exact provider-returned raw model identifier", str(exc.exception))

    def test_parse_ai_log_context_requires_non_empty_input_and_object_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            case1 = Path(tmpdir) / "invalid-input-string.json"
            case1.write_text(
                '{"stage":"Strategy Generation","model":"GPT-5","input":"prompt","output":{},"explanation":"x"}',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as exc:
                weex_contract_api.parse_ai_log_context_arg(f"@{case1}", "--ai-log")
            self.assertIn("input must be a non-empty JSON object", str(exc.exception))

            case2 = Path(tmpdir) / "invalid-output-array.json"
            case2.write_text(
                '{"stage":"Strategy Generation","model":"GPT-5","input":{"messages":[{"role":"user","content":"ping"}]},"output":[],"explanation":"x"}',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as exc:
                weex_contract_api.parse_ai_log_context_arg(f"@{case2}", "--ai-log")
            self.assertIn("output must be a JSON object", str(exc.exception))

            case3 = Path(tmpdir) / "invalid-empty-input.json"
            case3.write_text(
                '{"stage":"Strategy Generation","model":"GPT-5","input":{},"output":{},"explanation":"x"}',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as exc:
                weex_contract_api.parse_ai_log_context_arg(f"@{case3}", "--ai-log")
            self.assertIn("input must be a non-empty JSON object", str(exc.exception))

    def test_parse_ai_log_context_requires_file_reference(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            weex_contract_api.parse_ai_log_context_arg(
                '{"stage":"Strategy Generation","model":"gpt-5-2026-03-01","input":{"messages":[{"role":"user","content":"ping"}]},"output":{"symbol":"ETHUSDT","action":"BUY"},"explanation":"test"}',
                "--ai-log",
            )
        self.assertIn("@file.json", str(exc.exception))

    def test_validate_ai_log_payload_rejects_garbled_explanation_question_runs(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            weex_ai_api.validate_ai_log_payload(
                {
                    "stage": "Strategy Generation",
                    "model": "gpt-5-2026-03-01",
                    "input": {"messages": [{"role": "user", "content": "ping"}]},
                    "output": {"symbol": "ETHUSDT", "action": "BUY"},
                    "explanation": "??? STG ?????????????????????",
                },
                "AI log body",
            )
        self.assertIn("appears garbled", str(exc.exception))
        self.assertIn("PowerShell here-string pipelines", str(exc.exception))

    def test_validate_ai_log_payload_allows_normal_question_punctuation(self) -> None:
        payload = weex_ai_api.validate_ai_log_payload(
            {
                "stage": "Strategy Generation",
                "model": "gpt-5-2026-03-01",
                "input": {"messages": [{"role": "user", "content": "ping"}]},
                "output": {"symbol": "ETHUSDT", "action": "BUY"},
                "explanation": "Breakout confirmed??? Funding flipped negative, so reduce conviction but keep the long setup.",
            },
            "AI log body",
        )
        self.assertIn("Breakout confirmed???", payload["explanation"])

    def test_validate_ai_log_payload_rejects_replacement_character(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            weex_ai_api.validate_ai_log_payload(
                {
                    "stage": "Strategy Generation",
                    "model": "gpt-5-2026-03-01",
                    "input": {"messages": [{"role": "user", "content": "ping"}]},
                    "output": {"symbol": "ETHUSDT", "action": "BUY"},
                    "explanation": "The explanation already contains \ufffd replacement text.",
                },
                "AI log body",
            )
        self.assertIn("Unicode replacement character", str(exc.exception))

    def test_validate_place_pending_order_requires_price_for_stop(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            weex_contract_api.validate_place_pending_order_body(
                {
                    "symbol": "ethusdt",
                    "side": "sell",
                    "positionSide": "long",
                    "type": "STOP",
                    "quantity": "0.001",
                    "triggerPrice": "2500",
                    "clientAlgoId": "algo-001",
                }
            )
        self.assertIn("price is required", str(exc.exception))

    def test_build_ai_log_consistency_report_detects_symbol_mismatch(self) -> None:
        report = weex_contract_api.build_ai_log_consistency_report(
            "transaction.place_order",
            {
                "symbol": "ETHUSDT",
                "side": "SELL",
                "positionSide": "SHORT",
                "type": "LIMIT",
                "quantity": "0.001",
                "price": "2450",
            },
            {
                "stage": "Strategy Generation",
                "model": "GPT-5",
                "input": {"messages": [{"role": "user", "content": "Sell ETH if momentum weakens"}]},
                "output": {
                    "symbol": "BTCUSDT",
                    "action": "SELL",
                    "positionSide": "SHORT",
                    "type": "LIMIT",
                    "quantity": "0.001",
                    "price": "2450",
                },
                "explanation": "test",
            },
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["mismatches"][0]["field"], "symbol")

    def test_dry_run_rejects_ai_log_consistency_mismatch_before_request_preview(self) -> None:
        class FakeClient:
            def prepare_request(self, endpoint, query, body):
                raise AssertionError("mismatched AI log should be rejected before request preparation")

        with self.assertRaises(SystemExit) as exc:
            weex_contract_api.execute_endpoint_payload(
                client=FakeClient(),
                endpoint_key="transaction.place_order",
                query={},
                body={
                    "symbol": "ETHUSDT",
                    "side": "SELL",
                    "positionSide": "SHORT",
                    "type": "LIMIT",
                    "quantity": "0.001",
                    "price": "2450",
                    "timeInForce": "GTC",
                    "newClientOrderId": "test-ai-mismatch",
                },
                ai_log_context={
                    "stage": "Strategy Generation",
                    "model": "gpt-5-2026-03-01",
                    "input": {"messages": [{"role": "user", "content": "Sell ETH if momentum weakens"}]},
                    "output": {
                        "symbol": "BTCUSDT",
                        "action": "SELL",
                        "positionSide": "SHORT",
                        "type": "LIMIT",
                        "quantity": "0.001",
                        "price": "2450",
                    },
                    "explanation": "test",
                },
                dry_run=True,
                confirm_live=True,
            )

        self.assertIn("ai-log.output.symbol must match the request body", str(exc.exception))

    def test_normalize_trade_result_for_place_pending_order_checks_business_success(self) -> None:
        normalized = weex_contract_api.normalize_trade_result(
            "transaction.place_pending_order",
            {
                "ok": True,
                "status": 200,
                "data": {
                    "code": "00000",
                    "msg": "success",
                    "data": {
                        "orderId": "12345",
                        "clientAlgoId": "algo-001",
                        "success": False,
                        "errorCode": "40017",
                        "errorMessage": "invalid trigger price",
                    },
                },
            },
        )
        self.assertFalse(normalized["businessOk"])
        self.assertEqual(normalized["orderId"], 12345)
        self.assertIn("invalid trigger price", normalized["failureReason"])

    def test_normalize_trade_result_for_close_positions_detects_partial_failure(self) -> None:
        normalized = weex_contract_api.normalize_trade_result(
            "transaction.close_positions",
            {
                "ok": True,
                "status": 200,
                "data": {
                    "code": "00000",
                    "msg": "success",
                    "data": [
                        {"positionId": 1, "success": True, "successOrderId": 111},
                        {"positionId": 2, "success": False, "errorMessage": "position not found"},
                    ],
                },
            },
        )
        self.assertFalse(normalized["businessOk"])
        self.assertIn("position not found", normalized["failureReason"])

    def test_normalize_ai_endpoint_result_requires_business_success_code(self) -> None:
        normalized = weex_ai_api.normalize_ai_endpoint_result(
            "ai.trade.upload_ai_log",
            {
                "ok": True,
                "status": 200,
                "data": {
                    "code": "10001",
                    "msg": "allowlist denied",
                    "data": "upload failed",
                },
            },
        )
        self.assertTrue(normalized["transportOk"])
        self.assertFalse(normalized["businessOk"])
        self.assertIn("10001", normalized["failureReason"])

    def test_normalize_ai_endpoint_result_accepts_integer_zero_success_code(self) -> None:
        normalized = weex_ai_api.normalize_ai_endpoint_result(
            "ai.trade.upload_ai_log",
            {
                "ok": True,
                "status": 200,
                "data": {
                    "code": 0,
                    "msg": "success",
                    "data": "upload success",
                },
            },
        )
        self.assertTrue(normalized["transportOk"])
        self.assertTrue(normalized["businessOk"])
        self.assertEqual(
            normalized["normalizedResult"],
            {
                "code": "0",
                "msg": "success",
                "data": "upload success",
            },
        )

    def test_close_positions_without_symbol_is_not_auto_loggable(self) -> None:
        report = weex_contract_api.build_ai_log_consistency_report(
            "transaction.close_positions",
            {},
            {
                "stage": "Strategy Generation",
                "model": "GPT-5",
                "input": {"messages": [{"role": "user", "content": "Close ETH exposure"}]},
                "output": {"action": "close"},
                "explanation": "test",
            },
        )
        self.assertFalse(report["ok"])
        self.assertIn("requires a concrete symbol", report["mismatches"][0]["message"])

    def test_build_auto_ai_log_body_preserves_raw_input_and_output(self) -> None:
        endpoint = weex_contract_api.ENDPOINTS["transaction.place_pending_order"]
        ai_body = weex_contract_api.build_auto_ai_log_body(
            endpoint=endpoint,
            query={},
            body={
                "symbol": "ETHUSDT",
                "side": "BUY",
                "positionSide": "LONG",
                "type": "STOP_MARKET",
                "quantity": "0.0001",
                "triggerPrice": "2152.57",
                "clientAlgoId": "algo-001",
            },
            primary_trade_result={"orderId": 12345},
            ai_log_context={
                "stage": "Strategy Generation",
                "model": "gpt-5-2026-03-01",
                "input": {
                    "messages": [{"role": "user", "content": "Open a breakout long on ETHUSDT."}],
                    "market_context": {"symbol": "ETHUSDT", "price": 2148.27},
                },
                "output": {
                    "symbol": "ETHUSDT",
                    "action": "BUY",
                    "positionSide": "LONG",
                    "type": "STOP_MARKET",
                    "quantity": "0.0001",
                    "triggerPrice": "2152.57",
                },
                "explanation": "The supplied market snapshot and prompt support a breakout long.",
            },
            dry_run=False,
        )
        self.assertEqual(
            ai_body["input"],
            {
                "messages": [{"role": "user", "content": "Open a breakout long on ETHUSDT."}],
                "market_context": {"symbol": "ETHUSDT", "price": 2148.27},
            },
        )
        self.assertEqual(
            ai_body["output"],
            {
                "symbol": "ETHUSDT",
                "action": "BUY",
                "positionSide": "LONG",
                "type": "STOP_MARKET",
                "quantity": "0.0001",
                "triggerPrice": "2152.57",
            },
        )
        self.assertEqual(ai_body["orderId"], 12345)
        self.assertNotIn("aiDecision", ai_body["output"])
        self.assertNotIn("tradeIntent", ai_body["output"])
        self.assertNotIn("executionResult", ai_body["output"])

    def test_execute_endpoint_marks_ai_log_failure_as_non_retryable_after_trade_success(self) -> None:
        class FakeClient:
            def prepare_request(self, endpoint, query, body):
                return {"endpoint": endpoint.key, "query": query, "body": body}

            def send(self, prepared):
                return {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "code": "00000",
                        "msg": "success",
                        "data": {
                            "orderId": "12345",
                            "clientOrderId": "test-order-1",
                            "success": True,
                            "errorCode": None,
                            "errorMessage": None,
                        },
                    },
                }

        captured = {}
        ai_log_context = {
            "stage": "Strategy Generation",
            "model": "gpt-5-2026-03-01",
            "input": {"messages": [{"role": "user", "content": "Buy ETH"}]},
            "output": {
                "symbol": "ETHUSDT",
                "action": "BUY",
                "positionSide": "LONG",
                "type": "MARKET",
                "quantity": "0.001",
            },
            "explanation": "test",
        }

        with mock.patch.object(
            weex_contract_api,
            "maybe_execute_auto_ai_log",
            return_value={
                "enabled": True,
                "attempted": True,
                "ok": False,
                "failureReason": "upload denied",
            },
        ), mock.patch.object(
            weex_contract_api,
            "output_json",
            side_effect=lambda payload, pretty: captured.setdefault("payload", payload),
        ):
            exit_code = weex_contract_api.execute_endpoint(
                client=FakeClient(),
                endpoint_key="transaction.place_order",
                query={},
                body={
                    "symbol": "ETHUSDT",
                    "side": "BUY",
                    "positionSide": "LONG",
                    "type": "MARKET",
                    "quantity": "0.001",
                    "newClientOrderId": "test-order-1",
                },
                ai_log_context=ai_log_context,
                dry_run=False,
                confirm_live=True,
                pretty=False,
            )

        self.assertEqual(exit_code, weex_contract_api.EXIT_CODE_AI_LOG_FAILED)
        self.assertTrue(captured["payload"]["tradeExecuted"])
        self.assertTrue(captured["payload"]["aiLogUploadFailed"])
        self.assertFalse(captured["payload"]["retryTradeSafe"])
        self.assertIn("blindly retrying the trade may duplicate execution", captured["payload"]["nextAction"])
        self.assertEqual(captured["payload"]["aiLogFailureReason"], "upload denied")

    def test_maybe_dump_ai_log_request_writes_object_body_and_serialized_json(self) -> None:
        body = {
            "stage": "Strategy Generation",
            "model": "gpt-5-2026-03-01",
            "input": {"messages": [{"role": "user", "content": "ping"}]},
            "output": {"symbol": "ETHUSDT", "action": "BUY"},
            "explanation": "test",
        }
        prepared = {
            "method": "POST",
            "url": "https://example.com/capi/v3/order/uploadAiLog",
            "headers": {
                "Content-Type": "application/json",
                "ACCESS-KEY": "secret",
                "ACCESS-SIGN": "secret-sign",
            },
            "data": weex_ai_api.compact_json(body).encode("utf-8"),
        }

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            "os.environ",
            {weex_ai_api.AI_LOG_CAPTURE_ENV_VAR: tmpdir},
            clear=False,
        ):
            capture = weex_ai_api.maybe_dump_ai_log_request(
                "ai.trade.upload_ai_log",
                prepared,
                body,
                extra={"triggeredBy": "transaction.place_order"},
            )
            dump_path = Path(capture["path"])
            dump_payload = json.loads(dump_path.read_text(encoding="utf-8"))

        self.assertIsNotNone(capture)
        self.assertEqual(capture["bodyFieldTypes"]["input"], "object")
        self.assertEqual(capture["bodyFieldTypes"]["output"], "object")
        self.assertEqual(dump_payload["bodyFieldTypes"]["input"], "object")
        self.assertEqual(dump_payload["body"]["input"]["messages"][0]["content"], "ping")
        self.assertIn('"input":{"messages"', dump_payload["serializedBody"])
        self.assertNotIn('"input":"{', dump_payload["serializedBody"])


if __name__ == "__main__":
    unittest.main()
