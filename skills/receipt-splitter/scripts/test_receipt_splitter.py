import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from receipt_splitter import ReceiptSplitError, minimum_cash_flow, normalize_analysis


MEMBERS = [{"id": 1, "nickname": "小王"}, {"id": 2, "nickname": "小李"}, {"id": 3, "nickname": "小周"}]


class ReceiptSplitterTests(unittest.TestCase):
    def test_host_dinner_equal_split(self):
        result = normalize_analysis({
            "title": "午饭", "category": "餐饮", "total_cents": 30000,
            "payer_names": ["小王"], "participant_names": ["小李", "小周"],
            "split_method": "equal",
        }, MEMBERS)
        self.assertEqual(sum(row["amount_cents"] for row in result["bill"]["participants"]), 30000)
        self.assertEqual(result["bill"]["participants"], [{"user_id": 2, "amount_cents": 15000}, {"user_id": 3, "amount_cents": 15000}])
        self.assertEqual(result["transfers"], [{"from_user_id": 2, "to_user_id": 1, "amount_cents": 15000}, {"from_user_id": 3, "to_user_id": 1, "amount_cents": 15000}])

    def test_ratio_rounding_conserves_cents(self):
        result = normalize_analysis({
            "title": "采购", "total_cents": 10001, "payer_names": ["小王"],
            "participant_names": ["小王", "小李", "小周"], "split_method": "ratio",
            "participants": [{"name": "小王", "value": 2}, {"name": "小李", "value": 1}, {"name": "小周", "value": 1}],
        }, MEMBERS)
        self.assertEqual(sum(row["amount_cents"] for row in result["bill"]["participants"]), 10001)
        self.assertEqual(sum(row["amount_cents"] for row in result["bill"]["payers"]), 10001)

    def test_unknown_payer_is_rejected(self):
        with self.assertRaises(ReceiptSplitError) as error:
            normalize_analysis({"total_cents": 100, "payer_names": ["陌生人"]}, MEMBERS)
        self.assertEqual(error.exception.code, "unknown_member")

    def test_cash_flow_conservation(self):
        transfers = minimum_cash_flow([{"user_id": 1, "amount_cents": 100}], [{"user_id": 1, "amount_cents": 20}, {"user_id": 2, "amount_cents": 80}])
        self.assertEqual(transfers, [{"from_user_id": 2, "to_user_id": 1, "amount_cents": 80}])

    def test_multiple_payers_keep_recognized_amounts(self):
        result = normalize_analysis({
            "title": "聚餐", "total_cents": 30000,
            "payer_names": ["小王", "小李"],
            "payers": [{"name": "小王", "amount_cents": 20000}, {"name": "小李", "amount_cents": 10000}],
            "participant_names": ["小王", "小李", "小周"], "split_method": "equal",
        }, MEMBERS)
        self.assertEqual(result["bill"]["payers"], [{"user_id": 1, "amount_cents": 20000}, {"user_id": 2, "amount_cents": 10000}])

    def test_item_split_allocates_service_fee(self):
        result = normalize_analysis({
            "title": "火锅", "subtotal_cents": 20000, "total_cents": 22000,
            "payer_names": ["小王"], "participant_names": ["小李", "小周"], "split_method": "item",
            "items": [
                {"name": "锅底", "amount_cents": 10000, "participant_names": ["小李", "小周"]},
                {"name": "菜品", "amount_cents": 10000, "participant_names": ["小李"]},
            ],
        }, MEMBERS)
        self.assertEqual(sum(row["amount_cents"] for row in result["bill"]["participants"]), 22000)

    def test_host_rule_is_not_inverted(self):
        result = normalize_analysis({
            "title": "两张小票", "total_cents": 245700, "subtotal_cents": 245700,
            "payer_names": ["小王"], "participant_names": ["小王", "小李", "小周"], "split_method": "item",
            "items": [
                {"receipt_index": 1, "name": "午饭", "amount_cents": 96900, "participant_names": ["小王"]},
                {"receipt_index": 2, "name": "晚饭", "amount_cents": 148800, "participant_names": ["小王", "小李", "小周"]},
            ],
        }, MEMBERS)
        participants = {row["user_id"]: row["amount_cents"] for row in result["bill"]["participants"]}
        self.assertEqual(participants, {1: 146500, 2: 49600, 3: 49600})
        self.assertEqual(result["transfers"], [{"from_user_id": 2, "to_user_id": 1, "amount_cents": 49600}, {"from_user_id": 3, "to_user_id": 1, "amount_cents": 49600}])

    def test_receipt_total_adjustment_keeps_item_amounts(self):
        result = normalize_analysis({
            "title": "合并商品", "total_cents": 1000, "subtotal_cents": 1000,
            "payer_names": ["小王"], "participant_names": ["小王", "小李"], "split_method": "item",
            "items": [{"receipt_index": 1, "name": "午饭", "amount_cents": 900, "participant_names": ["小王", "小李"]}],
            "receipts": [{"receipt_index": 1, "total_cents": 1000}],
        }, MEMBERS)
        self.assertEqual(result["bill"]["items"][0]["amount_cents"], 1000)
        self.assertEqual(sum(row["amount_cents"] for row in result["bill"]["participants"]), 1000)

    def test_selected_payer_overrides_missing_model_payer(self):
        result = normalize_analysis({
            "title": "午饭", "total_cents": 1000, "subtotal_cents": 1000,
            "payer_names": [], "participant_names": ["小王", "小李"], "split_method": "equal",
            "ambiguities": ["无法从小票判断实际付款人"],
        }, MEMBERS, actual_payer_id=1)
        self.assertEqual(result["bill"]["payers"], [{"user_id": 1, "amount_cents": 1000}])
        self.assertEqual(result["transfers"], [{"from_user_id": 2, "to_user_id": 1, "amount_cents": 500}])

    def test_unknown_model_participant_falls_back_to_group_participants(self):
        result = normalize_analysis({
            "title": "午饭", "total_cents": 1000, "subtotal_cents": 1000,
            "participant_names": ["小王", "小李"], "split_method": "item",
            "items": [{"name": "午饭", "amount_cents": 1000, "participant_names": ["顾客"]}],
        }, MEMBERS, actual_payer_id=1)
        self.assertEqual(result["bill"]["items"][0]["participant_ids"], [1, 2])
        self.assertEqual(result["transfers"], [{"from_user_id": 2, "to_user_id": 1, "amount_cents": 500}])


if __name__ == "__main__":
    unittest.main()
