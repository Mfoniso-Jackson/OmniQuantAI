#!/usr/bin/env python3
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import weex_trade_data_aggregator as aggregator
import weex_contract_api
import weex_trade_risk_review as risk_review


class ContractOnlyAggregatorTests(unittest.TestCase):
    def test_parser_accepts_futures_without_public_trading_mode_switch(self) -> None:
        parser = aggregator.build_parser()

        args = parser.parse_args(
            [
                "collect-account-risk",
                "--profile",
                "main",
                "--market",
                "futures",
            ]
        )

        self.assertEqual(args.market, "futures")
        profile_args = parser.parse_args(["collect-profile", "--profile", "main"])
        self.assertEqual(profile_args.period, "auto")
        with self.assertRaises(SystemExit):
            parser.parse_args(["collect-account-risk", "--profile", "main", "--market", "spot"])
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "collect-account-risk",
                    "--profile",
                    "main",
                    "--market",
                    "futures",
                    "--trading-mode",
                    "live",
                ]
            )

    def test_replay_and_profile_parser_accept_live_confirmation_for_read_only_post(self) -> None:
        parser = aggregator.build_parser()

        replay_args = parser.parse_args(
            ["collect-replay", "--profile", "main", "--confirm-live"]
        )
        profile_args = parser.parse_args(
            ["collect-profile", "--profile", "main", "--confirm-live"]
        )

        self.assertTrue(replay_args.confirm_live)
        self.assertTrue(profile_args.confirm_live)

    def test_fetch_futures_bills_requires_confirmation_before_send(self) -> None:
        fetcher = aggregator.WeexApiFetcher()

        with mock.patch.object(fetcher, "_send_contract_request") as send_mock:
            with self.assertRaisesRegex(aggregator.AggregationInputError, "confirm-live"):
                fetcher.fetch_futures_bills(
                    profile_name="main",
                    start_ms=0,
                    end_ms=aggregator.MIN_SPLIT_WINDOW_MS,
                    symbol="BTCUSDT",
                )

        send_mock.assert_not_called()

    def test_collect_replay_requires_confirmation_before_any_fetch(self) -> None:
        fetcher = mock.Mock()
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        with self.assertRaisesRegex(aggregator.AggregationInputError, "confirm-live"):
            trade_aggregator.collect_replay_payload(
                profile_name="main",
                market="futures",
                trading_mode="live",
                period="7d",
            )

        fetcher.fetch_futures_balance.assert_not_called()

    def test_rejects_non_futures_market_before_fetching(self) -> None:
        fetcher = mock.Mock()
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        with self.assertRaises(aggregator.AggregationInputError) as exc_info:
            trade_aggregator.collect_account_risk_payload(profile_name="main", market="spot")

        self.assertIn("futures", str(exc_info.exception))
        fetcher.fetch_futures_balance.assert_not_called()

    def test_rejects_non_live_trading_mode_before_fetching(self) -> None:
        fetcher = mock.Mock()
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        with self.assertRaises(aggregator.AggregationInputError) as exc_info:
            trade_aggregator.collect_account_risk_payload(
                profile_name="main",
                market="futures",
                trading_mode="demo",
            )

        self.assertIn("live", str(exc_info.exception))
        fetcher.fetch_futures_balance.assert_not_called()

    def test_live_environment_prefix_is_real_contract_only(self) -> None:
        environment = aggregator._environment_for_trading_mode("live", "futures")

        self.assertEqual(environment["trading_mode"], "live")
        self.assertTrue(environment["uses_real_funds"])
        self.assertEqual(aggregator._user_environment_prefix(environment, "zh"), "当前交易环境：真实盘")
        self.assertEqual(aggregator._user_environment_prefix(environment, "en"), "Current trading mode: real trading")

    def test_fetch_futures_balance_uses_live_contract_endpoint(self) -> None:
        fetcher = aggregator.WeexApiFetcher()

        with mock.patch.object(
            fetcher,
            "_send_contract_request",
            return_value={"balance": []},
        ) as send_mock:
            payload = fetcher.fetch_futures_balance(profile_name="main", trading_mode="live")

        self.assertEqual(payload, {"balance": []})
        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.kwargs["endpoint_key"], "account.get_account_balance")

    def test_build_contract_client_uses_profile_runtime_loader(self) -> None:
        fetcher = aggregator.WeexApiFetcher()
        profile = types.SimpleNamespace(name="main", contract_base_url="")
        contract_api = types.SimpleNamespace(
            DEFAULT_BASE_URL=weex_contract_api.DEFAULT_BASE_URL,
            DEFAULT_LOCALE=weex_contract_api.DEFAULT_LOCALE,
            DEFAULT_TIMEOUT=weex_contract_api.DEFAULT_TIMEOUT,
            WeexContractClient=mock.Mock(return_value=mock.Mock()),
            ensure_private_runtime_ready=mock.Mock(),
            refresh_agent_records=mock.Mock(),
            require_private_profile=mock.Mock(),
            resolve_runtime_profile=mock.Mock(return_value=profile),
        )

        with mock.patch.object(fetcher, "_contract_module", return_value=contract_api), mock.patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            returned_contract_api, client = fetcher._build_contract_client("main")

        self.assertIs(returned_contract_api, contract_api)
        self.assertIs(client, contract_api.WeexContractClient.return_value)
        contract_api.WeexContractClient.assert_called_once()
        client_kwargs = contract_api.WeexContractClient.call_args.kwargs
        self.assertIsNone(client_kwargs["api_key"])
        self.assertIsNone(client_kwargs["api_secret"])
        self.assertIsNone(client_kwargs["api_passphrase"])
        self.assertEqual(client_kwargs["profile_name"], "main")

    def test_order_collection_uses_existing_contract_order_endpoints(self) -> None:
        fetcher = aggregator.WeexApiFetcher()

        cases = (
            (
                fetcher.fetch_futures_open_orders,
                "transaction.get_current_order_status",
            ),
            (
                fetcher.fetch_futures_pending_orders,
                "transaction.get_current_pending_orders",
            ),
        )
        for fetch_method, expected_endpoint_key in cases:
            with self.subTest(endpoint=expected_endpoint_key), mock.patch.object(
                fetcher,
                "_send_contract_request",
                return_value={"orders": []},
            ) as send_mock:
                payload = fetch_method(profile_name="main", symbol="ethusdt", trading_mode="live")

            self.assertEqual(payload, {"orders": []})
            send_mock.assert_called_once()
            call_kwargs = send_mock.call_args.kwargs
            self.assertEqual(call_kwargs["endpoint_key"], expected_endpoint_key)
            self.assertIn(call_kwargs["endpoint_key"], weex_contract_api.ENDPOINTS)
            self.assertEqual(call_kwargs["query"], {"symbol": "ETHUSDT"})
            self.assertIsNone(call_kwargs.get("body"))

    def test_fetch_futures_orders_paginates_until_page_is_exhausted(self) -> None:
        fetcher = aggregator.WeexApiFetcher()
        first_page = [{"orderId": index, "symbol": "BTCUSDT"} for index in range(1000)]
        second_page = [{"orderId": 1001, "symbol": "BTCUSDT"}]

        with mock.patch.object(
            fetcher,
            "_send_contract_request",
            side_effect=[first_page, second_page],
        ) as send_mock:
            payload = fetcher.fetch_futures_orders(
                profile_name="main",
                start_ms=10,
                end_ms=20,
                symbol="BTCUSDT",
            )

        self.assertEqual(len(payload), 1001)
        self.assertEqual([call.kwargs["query"]["page"] for call in send_mock.call_args_list], [0, 1])

    def test_fetch_futures_fills_splits_full_windows_before_returning_rows(self) -> None:
        fetcher = aggregator.WeexApiFetcher()
        queries: list[dict[str, object]] = []

        def fake_send(**kwargs: object) -> list[dict[str, object]]:
            query = dict(kwargs["query"])
            queries.append(query)
            span = int(query["endTime"]) - int(query["startTime"])
            if span > aggregator.MIN_SPLIT_WINDOW_MS:
                return [
                    {
                        "id": index,
                        "orderId": index,
                        "time": query["startTime"],
                        "symbol": "BTCUSDT",
                    }
                    for index in range(aggregator.FUTURES_FILL_LIMIT)
                ]
            return [
                {
                    "id": f"{query['startTime']}-{query['endTime']}",
                    "orderId": query["startTime"],
                    "time": query["startTime"],
                    "symbol": "BTCUSDT",
                }
            ]

        with mock.patch.object(fetcher, "_send_contract_request", side_effect=fake_send):
            payload = fetcher.fetch_futures_fills(
                profile_name="main",
                start_ms=0,
                end_ms=2 * aggregator.MIN_SPLIT_WINDOW_MS,
                symbol="BTCUSDT",
            )

        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)
        self.assertGreater(len(queries), 1)

    def test_fetch_futures_bills_consumes_next_key_cursor(self) -> None:
        fetcher = aggregator.WeexApiFetcher()
        responses = [
            {
                "hasNextPage": True,
                "nextKey": {"nextKeyId": 101, "nextKeyTime": 1001},
                "items": [{"billId": 1, "time": 1000, "symbol": "BTCUSDT"}],
            },
            {
                "hasNextPage": False,
                "items": [{"billId": 2, "time": 999, "symbol": "BTCUSDT"}],
            },
        ]

        with mock.patch.object(fetcher, "_send_contract_request", side_effect=responses) as send_mock:
            payload = fetcher.fetch_futures_bills(
                profile_name="main",
                start_ms=0,
                end_ms=aggregator.MIN_SPLIT_WINDOW_MS,
                symbol="BTCUSDT",
                confirm_live=True,
            )

        self.assertEqual([item["billId"] for item in payload], [1, 2])
        self.assertEqual(send_mock.call_args_list[1].kwargs["body"]["nextKeyId"], 101)
        self.assertEqual(send_mock.call_args_list[1].kwargs["body"]["nextKeyTime"], 1001)

    def test_historical_pending_orders_split_has_more_windows(self) -> None:
        fetcher = aggregator.WeexApiFetcher()
        queries: list[dict[str, object]] = []

        def fake_send(**kwargs: object) -> dict[str, object]:
            query = dict(kwargs["query"])
            queries.append(query)
            span = int(query["endTime"]) - int(query["startTime"])
            return {
                "orders": [
                    {
                        "algoId": f"{query['startTime']}-{query['endTime']}",
                        "createTime": query["startTime"],
                        "symbol": "BTCUSDT",
                    }
                ],
                "hasMore": span > aggregator.MIN_SPLIT_WINDOW_MS,
            }

        with mock.patch.object(fetcher, "_send_contract_request", side_effect=fake_send):
            payload = fetcher.fetch_futures_historical_pending_orders(
                profile_name="main",
                start_ms=0,
                end_ms=2 * aggregator.MIN_SPLIT_WINDOW_MS,
                symbol="BTCUSDT",
            )

        self.assertIsInstance(payload, list)
        self.assertGreater(len(queries), 1)
        self.assertTrue(all("page" not in query for query in queries))

    def test_historical_pending_orders_marks_minimum_window_truncated(self) -> None:
        fetcher = aggregator.WeexApiFetcher()
        row = {"algoId": "stalled", "createTime": 0, "symbol": "BTCUSDT"}

        with mock.patch.object(
            fetcher,
            "_send_contract_request",
            return_value={"orders": [row], "hasMore": True},
        ):
            payload = fetcher.fetch_futures_historical_pending_orders(
                profile_name="main",
                start_ms=0,
                end_ms=aggregator.MIN_SPLIT_WINDOW_MS,
                symbol="BTCUSDT",
            )

        self.assertEqual(payload["items"], [row])
        self.assertTrue(payload["_meta"]["partial"])
        self.assertIn(
            "futures_historical_pending_orders_window_truncated",
            payload["_meta"]["degraded_reasons"],
        )

    def test_order_risk_payload_exposes_analysis_context(self) -> None:
        fetcher = mock.Mock()
        fetcher.fetch_futures_balance.return_value = [
            {
                "asset": "USDT",
                "balance": "1000",
                "availableBalance": "620",
                "unrealizePnl": "12",
            }
        ]
        fetcher.fetch_futures_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "size": "0.01",
                "openValue": "650",
                "leverage": "20",
            }
        ]
        fetcher.fetch_futures_open_orders.return_value = [
            {
                "orderId": 101,
                "symbol": "BTCUSDT",
                "side": "BUY",
                "positionSide": "LONG",
                "type": "LIMIT",
                "origQty": "0.02",
                "executedQty": "0.01",
                "price": "64000",
            }
        ]
        fetcher.fetch_futures_pending_orders.return_value = [
            {
                "algoId": 201,
                "symbol": "BTCUSDT",
                "side": "SELL",
                "positionSide": "LONG",
                "orderType": "TAKE_PROFIT_MARKET",
                "quantity": "0.01",
                "triggerPrice": "85000",
                "reduceOnly": True,
            },
            {
                "algoId": 202,
                "symbol": "BTCUSDT",
                "side": "SELL",
                "positionSide": "LONG",
                "orderType": "STOP_MARKET",
                "quantity": "0.01",
                "triggerPrice": "60000",
                "reduceOnly": True,
            },
        ]
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        payload = trade_aggregator.collect_order_risk_payload(
            profile_name="main",
            market="futures",
            trading_mode="live",
            raw_order={
                "symbol": "btcusdt",
                "side": "BUY",
                "positionSide": "LONG",
                "type": "MARKET",
                "quantity": "0.01",
            },
        )

        self.assertEqual(payload["account_snapshot"]["balance"], 1000.0)
        self.assertEqual(payload["account_snapshot"]["available_balance"], 620.0)
        self.assertEqual(payload["positions"][0]["notional"], 650.0)
        self.assertEqual(payload["order_preview"]["market"], "futures")
        self.assertEqual(payload["open_orders"][0]["order_id"], "101")
        self.assertEqual(payload["conditional_orders"][0]["tp_trigger_price"], 85000.0)
        self.assertEqual(payload["conditional_orders"][1]["sl_trigger_price"], 60000.0)

    def test_order_risk_payload_converts_futures_contracts_once(self) -> None:
        fetcher = mock.Mock()
        fetcher.fetch_futures_symbol_facts.return_value = {
            "symbols": [{"symbol": "BTCUSDT", "contractVal": "0.0001"}],
        }
        fetcher.fetch_futures_balance.return_value = []
        fetcher.fetch_futures_positions.return_value = []
        fetcher.fetch_futures_open_orders.return_value = []
        fetcher.fetch_futures_pending_orders.return_value = []
        fetcher.fetch_futures_orders.return_value = []
        fetcher.fetch_futures_latest_price.return_value = {
            "symbol": "BTCUSDT",
            "price": "60000",
        }

        payload = aggregator.TradeDataAggregator(fetcher=fetcher).collect_order_risk_payload(
            profile_name="main",
            market="futures",
            trading_mode="live",
            raw_order={
                "symbol": "BTCUSDT",
                "side": "BUY",
                "positionSide": "LONG",
                "type": "LIMIT",
                "timeInForce": "GTC",
                "quantity": "13",
                "quantity_unit": "CONTRACTS",
                "price": "60000",
            },
        )

        self.assertEqual(payload["order_preview"]["quantity"], "0.0013")
        self.assertEqual(payload["order_preview"]["quantity_unit"], "BASE_ASSET")
        self.assertEqual(payload["quantity_semantics"]["contract_val"], "0.0001")
        self.assertEqual(payload["normalized_order"]["quantity"], "0.0013")
        self.assertNotIn("quantity_unit", payload["normalized_order"])
        fetcher.fetch_futures_symbol_facts.assert_called_once_with(
            profile_name="main",
            symbol="BTCUSDT",
        )

    def test_account_risk_normalizes_separated_position_identity(self) -> None:
        fetcher = mock.Mock()
        fetcher.fetch_futures_balance.return_value = []
        fetcher.fetch_futures_positions.return_value = [
            {
                "id": 785178733873988293,
                "symbol": "ETHUSDT",
                "positionSide": "LONG",
                "size": "0.001",
                "separatedMode": "SEPARATED",
                "separatedOpenOrderId": 785178733848822469,
            }
        ]
        fetcher.fetch_futures_open_orders.return_value = []
        fetcher.fetch_futures_pending_orders.return_value = []
        fetcher.fetch_futures_orders.return_value = []

        payload = aggregator.TradeDataAggregator(fetcher=fetcher).collect_account_risk_payload(
            profile_name="main",
            market="futures",
            trading_mode="live",
            symbol="ETHUSDT",
        )

        self.assertEqual(payload["positions"][0]["position_id"], "785178733873988293")
        self.assertEqual(
            payload["positions"][0]["separated_open_order_id"],
            "785178733848822469",
        )

    def test_order_risk_payload_includes_recent_order_history_for_frequency_alert(self) -> None:
        now_ms = 1710004200000
        fetcher = mock.Mock()
        fetcher.fetch_futures_balance.return_value = [
            {
                "asset": "USDT",
                "balance": "1000",
                "availableBalance": "620",
            }
        ]
        fetcher.fetch_futures_positions.return_value = []
        fetcher.fetch_futures_open_orders.return_value = []
        fetcher.fetch_futures_pending_orders.return_value = []
        fetcher.fetch_futures_orders.return_value = [
            {
                "orderId": 100 + index,
                "symbol": "BTCUSDT",
                "side": "BUY",
                "positionSide": "LONG",
                "type": "MARKET",
                "status": "FILLED",
                "origQty": "0.001",
                "executedQty": "0.001",
                "time": now_ms - (index * 5 * 60 * 1000),
            }
            for index in range(7)
        ]
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        with mock.patch.object(aggregator, "_now_ms", return_value=now_ms):
            payload = trade_aggregator.collect_order_risk_payload(
                profile_name="main",
                market="futures",
                trading_mode="live",
                raw_order={
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "positionSide": "LONG",
                    "type": "MARKET",
                    "quantity": "0.001",
                },
            )

        self.assertEqual(len(payload["recent_orders"]), 7)
        fetcher.fetch_futures_orders.assert_called_once_with(
            profile_name="main",
            start_ms=now_ms - aggregator.RECENT_ORDER_LOOKBACK_MS,
            end_ms=now_ms,
            symbol="BTCUSDT",
            trading_mode="live",
        )
        result = risk_review.analyze_order_risk(payload)
        self.assertIn("high_trade_frequency", {alert["type"] for alert in result["alerts"]})

    def test_account_risk_marks_partial_when_recent_order_history_is_unavailable(self) -> None:
        fetcher = mock.Mock()
        fetcher.fetch_futures_balance.return_value = [
            {
                "asset": "USDT",
                "balance": "1000",
                "availableBalance": "620",
            }
        ]
        fetcher.fetch_futures_positions.return_value = []
        fetcher.fetch_futures_open_orders.return_value = []
        fetcher.fetch_futures_pending_orders.return_value = []
        fetcher.fetch_futures_orders.side_effect = aggregator.AggregationInputError("order history unavailable")
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        payload = trade_aggregator.collect_account_risk_payload(
            profile_name="main",
            market="futures",
            trading_mode="live",
            symbol="BTCUSDT",
        )

        self.assertTrue(payload["partial"])
        self.assertIn("recent_order_history_unavailable", payload["degraded_reasons"])
        self.assertEqual(payload["recent_orders"], [])

    def test_collect_replay_payload_includes_futures_fills_bills_and_price_series(self) -> None:
        fetcher = mock.Mock()
        fetcher.fetch_futures_balance.return_value = {
            "asset": "USDT",
            "balance": "1000",
            "availableBalance": "620",
            "unrealizePnl": "30",
        }
        fetcher.fetch_futures_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "side": "LONG",
                "marginType": "CROSSED",
                "separatedMode": "COMBINED",
                "size": "0.01",
                "openValue": "650",
            }
        ]
        fetcher.fetch_futures_orders.return_value = [
            {
                "symbol": "BTCUSDT",
                "orderId": 11,
                "side": "BUY",
                "positionSide": "LONG",
                "type": "LIMIT",
                "status": "FILLED",
                "origQty": "0.01",
                "executedQty": "0.01",
                "cumQuote": "650",
                "avgPrice": "65000",
                "time": 1710000000000,
            }
        ]
        fetcher.fetch_futures_historical_pending_orders.return_value = []
        fetcher.fetch_futures_fills.return_value = [
            {
                "id": 21,
                "orderId": 11,
                "symbol": "BTCUSDT",
                "side": "BUY",
                "positionSide": "LONG",
                "price": "65000",
                "qty": "0.01",
                "quoteQty": "650",
                "realizedPnl": "12",
                "commission": "0.5",
                "time": 1710003600000,
            }
        ]
        fetcher.fetch_futures_bills.return_value = {
            "items": [
                {
                    "billId": 31,
                    "asset": "USDT",
                    "symbol": "BTCUSDT",
                    "income": "12",
                    "incomeType": "position_close_long",
                    "fillFee": "0.5",
                    "time": 1710003600000,
                }
            ]
        }
        fetcher.fetch_futures_klines.return_value = [
            [1710000000000, "64000", "66000", "63500", "65000", "100", 1710003599999, "6500000", 120, "55", "3575000"]
        ]
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        result = trade_aggregator.collect_replay_payload(
            profile_name="main",
            market="futures",
            trading_mode="live",
            period="7d",
            symbol="BTCUSDT",
            confirm_live=True,
        )

        self.assertEqual(result["market"], "futures")
        self.assertEqual(result["trading_mode"], "live")
        self.assertEqual(result["balances"][0]["account_scope"], "personal_futures")
        self.assertEqual(result["positions"][0]["symbol"], "BTCUSDT")
        self.assertEqual(result["orders"][0]["status"], "FILLED")
        self.assertEqual(result["fills"][0]["realized_pnl"], 12.0)
        self.assertEqual(result["bills"][0]["type"], "position_close_long")
        self.assertEqual(result["price_series"][0]["close"], 65000.0)
        self.assertEqual(result["closed_trade_count"], 1)
        fetcher.fetch_futures_fills.assert_called()
        fetcher.fetch_futures_bills.assert_called()
        fetcher.fetch_futures_klines.assert_called_once()

    def test_collect_profile_default_keeps_30d_when_closed_trade_sample_is_sufficient(self) -> None:
        fetcher = mock.Mock()
        fetcher.fetch_futures_balance.return_value = []
        fetcher.fetch_futures_positions.return_value = []
        fetcher.fetch_futures_orders.return_value = []
        fetcher.fetch_futures_historical_pending_orders.return_value = []
        fetcher.fetch_futures_fills.return_value = []
        fetcher.fetch_futures_bills.return_value = [
            {"incomeType": "position_close_long", "income": "1", "time": 1710000000000 + index}
            for index in range(12)
        ]
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        with mock.patch.object(aggregator, "_now_ms", return_value=1710000000000):
            result = trade_aggregator.collect_profile_payload(
                profile_name="main",
                market="futures",
                trading_mode="live",
                confirm_live=True,
            )

        self.assertEqual(result["period"], "30d")
        self.assertEqual(result["selected_period"], "30d")
        self.assertFalse(result["fallback_applied"])
        self.assertEqual(result["closed_trade_count"], 12)
        fetcher.fetch_futures_bills.assert_called_once()

    def test_collect_profile_default_expands_when_30d_closed_trade_sample_is_too_small(self) -> None:
        fetcher = mock.Mock()
        fetcher.fetch_futures_balance.return_value = []
        fetcher.fetch_futures_positions.return_value = []
        fetcher.fetch_futures_orders.return_value = []
        fetcher.fetch_futures_historical_pending_orders.return_value = []
        fetcher.fetch_futures_fills.return_value = []
        fetcher.fetch_futures_bills.side_effect = [
            [
                {"incomeType": "position_close_long", "income": "1", "time": 1710000000000 + index}
                for index in range(4)
            ],
            [
                {"incomeType": "position_close_long", "income": "1", "time": 1710000000000 + index}
                for index in range(12)
            ],
        ]
        trade_aggregator = aggregator.TradeDataAggregator(fetcher=fetcher)

        with mock.patch.object(aggregator, "_now_ms", return_value=1710000000000):
            result = trade_aggregator.collect_profile_payload(
                profile_name="main",
                market="futures",
                trading_mode="live",
                confirm_live=True,
            )

        self.assertEqual(result["period"], "90d")
        self.assertEqual(result["selected_period"], "90d")
        self.assertTrue(result["fallback_applied"])
        self.assertEqual(
            result["fallback_periods_considered"],
            [
                {"period": "30d", "closed_trade_count": 4},
                {"period": "90d", "closed_trade_count": 12},
            ],
        )
        self.assertEqual(fetcher.fetch_futures_bills.call_count, 2)

    def test_main_exits_for_rejected_market(self) -> None:
        with self.assertRaises(SystemExit) as exc_info:
            aggregator.main(["collect-account-risk", "--profile", "main", "--market", "spot"])

        self.assertEqual(exc_info.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
