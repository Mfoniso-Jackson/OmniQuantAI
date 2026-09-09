#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from weex_order_quantity import (  # noqa: E402
    BASE_ASSET,
    CONTRACTS,
    QuantitySemanticsError,
    normalize_order_quantity,
)


class OrderQuantitySemanticsTests(unittest.TestCase):
    def test_base_asset_quantity_is_not_scaled_by_contract_value(self) -> None:
        result = normalize_order_quantity(
            market="FUTURES",
            order={"quantity": "0.0013", "quantity_unit": BASE_ASSET},
            symbol_facts={"contractVal": "0.0001"},
        )

        self.assertEqual(result["input_quantity"], "0.0013")
        self.assertEqual(result["input_unit"], BASE_ASSET)
        self.assertEqual(result["api_quantity"], "0.0013")
        self.assertEqual(result["api_quantity_unit"], BASE_ASSET)
        self.assertEqual(result["contract_val"], "0.0001")

    def test_contract_quantity_is_converted_to_base_asset_quantity(self) -> None:
        result = normalize_order_quantity(
            market="FUTURES",
            order={"quantity": "13", "quantity_unit": CONTRACTS},
            symbol_facts={"contractVal": "0.0001"},
        )

        self.assertEqual(result["input_quantity"], "13")
        self.assertEqual(result["input_unit"], CONTRACTS)
        self.assertEqual(result["api_quantity"], "0.0013")
        self.assertEqual(result["api_quantity_unit"], BASE_ASSET)
        self.assertEqual(result["contract_val"], "0.0001")

    def test_contract_quantity_fails_closed_without_contract_value(self) -> None:
        with self.assertRaises(QuantitySemanticsError) as context:
            normalize_order_quantity(
                market="FUTURES",
                order={"quantity": "13", "quantity_unit": CONTRACTS},
                symbol_facts={},
            )

        self.assertEqual(context.exception.code, "CONTRACT_VALUE_REQUIRED")

    def test_unknown_quantity_unit_is_rejected(self) -> None:
        with self.assertRaises(QuantitySemanticsError) as context:
            normalize_order_quantity(
                market="FUTURES",
                order={"quantity": "1", "quantity_unit": "LOTS"},
                symbol_facts={"contractVal": "0.001"},
            )

        self.assertEqual(context.exception.code, "QUANTITY_UNIT_UNSUPPORTED")

    def test_explicit_unit_can_be_required_for_structured_orders(self) -> None:
        with self.assertRaises(QuantitySemanticsError) as context:
            normalize_order_quantity(
                market="FUTURES",
                order={"quantity": "1"},
                symbol_facts={"contractVal": "0.001"},
                require_explicit_unit=True,
            )

        self.assertEqual(context.exception.code, "QUANTITY_UNIT_REQUIRED")

    def test_non_futures_market_is_rejected_by_ai_wars_distribution(self) -> None:
        with self.assertRaises(QuantitySemanticsError) as context:
            normalize_order_quantity(
                market="SPOT",
                order={"quantity": "1", "quantity_unit": BASE_ASSET},
                symbol_facts={"contractVal": "0.001"},
            )

        self.assertEqual(context.exception.code, "MARKET_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
