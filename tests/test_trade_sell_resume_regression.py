from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / "agent" / "profile_prestige_action.py"


def _load_trade_actions(state: dict) -> dict:
    """Run the production state transitions without importing Maa or opening a game."""
    names = {
        "_manual_two_city_active_leg",
        "_manual_two_city_legs",
        "_manual_two_city_detect_current_city",
        "_manual_two_city_set_active_leg_by_city",
        "_manual_two_city_next_leg_after_current",
        "_manual_two_city_run_mode",
        "_manual_two_city_until_fatigue_exhausted",
        "_manual_two_city_leg_run_marker",
        "_manual_two_city_buy_book_usage",
        "_manual_two_city_clear_existing_cargo_limit",
        "_manual_two_city_clear_buy_selection_state",
        "_manual_two_city_texts_contain",
        "ManualTwoCityBusinessAfterDrinkReturnCityAction",
        "ManualTwoCityBusinessCurrentCityReadyAction",
        "ManualTwoCityBusinessAfterSellAction",
        "ManualTwoCityBusinessBuyPageReadyAction",
    }
    constants = {
        "MANUAL_TWO_CITY_TASK_ENTRY",
        "MANUAL_TWO_CITY_RUN_MODE_ONE_ROUND",
        "MANUAL_TWO_CITY_RUN_MODE_UNTIL_FATIGUE_EXHAUSTED",
        "MANUAL_TWO_CITY_TERMINAL_ONE_ROUND_COMPLETE",
        "TRADE_SWITCH_TO_BUY_ROI",
        "TRADE_SWITCH_TO_BUY_TARGET",
        "BUY_BOOK_MENU_TEXTS",
        "BUY_BOOK_POPUP_TEXTS",
        "PRE_BUY_CLEANUP_WARN_RATIO",
    }
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"), filename=str(SOURCE))
    namespace = {
        "CustomAction": object,
        "_manual_two_city_state": lambda: state,
        "_argv_param": lambda argv: argv.params,
        "_ocr_texts": lambda argv: argv.texts,
        "_ocr_entries": lambda argv: [],
        "clean_text": lambda text: str(text).strip(),
        "normalize_city_name": lambda city: str(city).strip(),
        "load_city_names": lambda: ["岚心城", "海角城"],
        "_all_buy_goods_by_city": lambda: {},
        "_append_user_log": Mock(),
        "_json_payload": Mock(),
        "_manual_two_city_click_ocr_text": Mock(return_value=(True, ["我要买"])),
        "_manual_two_city_read_buy_page_cargo_load": Mock(
            return_value=({"used": 29, "capacity": 1300, "ratio": 29 / 1300}, [], False)
        ),
    }
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in constants:
                    namespace[target.id] = ast.literal_eval(node.value)
                    found.add(target.id)
    missing = (names | constants) - found
    if missing:
        raise AssertionError(f"Production trade definitions missing: {sorted(missing)}")
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


class TradeSellResumeRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.legs = [
            {"buy_city": "岚心城", "sell_city": "海角城", "restock": 3, "goods": ["岚心锦服"]},
            {"buy_city": "海角城", "sell_city": "岚心城", "restock": 3, "goods": ["珍珠"]},
        ]
        self.old_marker = "1|0|岚心城|海角城"
        self.old_usage = {"marker": self.old_marker, "attempted": True, "requested": 3, "used": 3}
        self.state = {
            "result": {"summary": {"legs": self.legs}},
            "run_mode": "until_fatigue_exhausted",
            "completed_rounds": 1,
            "active_leg_index": 1,
            "trade_phase": "sell",
            "drink_resume_phase": "sell",
            "current_city": "岚心城",
            "buy_book_usage_by_leg": {self.old_marker: dict(self.old_usage)},
        }
        self.trade = _load_trade_actions(self.state)

    def _action(self, name: str, city: str = "", source: str = "main_map") -> bool:
        argv = SimpleNamespace(params={"source": source}, texts=["访问城市", city] if city else [])
        return self.trade[name]().run(None, argv)

    def _resume_sell(self, city: str, source: str = "main_map") -> None:
        self.assertTrue(self._action("ManualTwoCityBusinessAfterDrinkReturnCityAction"))
        self.assertTrue(self._action("ManualTwoCityBusinessCurrentCityReadyAction", city, source))

    def _open_buy_page(self, city: str) -> None:
        self.assertTrue(self._action("ManualTwoCityBusinessBuyPageReadyAction", city))

    def test_sell_resume_keeps_unsold_leg_at_destination(self) -> None:
        for leg_index in (0, 1):
            for source in ("main_map", "city_page"):
                with self.subTest(leg_index=leg_index, source=source):
                    self.state.update(active_leg_index=leg_index, trade_phase="sell")
                    destination = self.legs[leg_index]["sell_city"]
                    self._resume_sell(destination, source)
                    self.assertEqual(self.state["active_leg_index"], leg_index)
                    self.assertEqual(self.state["trade_phase"], "sell")
                    self.assertEqual(self.state["current_city"], destination)
                    self.assertEqual(self.state["completed_rounds"], 1)

    def test_last_sell_advances_round_and_does_not_reuse_previous_buy_books(self) -> None:
        self._resume_sell("岚心城")
        self.assertTrue(self._action("ManualTwoCityBusinessAfterSellAction"))
        self._open_buy_page("岚心城")

        self.assertEqual(self.state["completed_rounds"], 2)
        self.assertEqual(self.state["active_leg_index"], 0)
        self.assertEqual(self.state["trade_phase"], "buy")
        self.assertEqual(self.trade["_manual_two_city_leg_run_marker"](), "2|0|岚心城|海角城")
        self.assertEqual(self.trade["_manual_two_city_buy_book_usage"](), {})
        self.assertEqual(self.state["buy_book_usage_by_leg"][self.old_marker], self.old_usage)

    def test_first_sell_advances_to_return_leg_without_advancing_round(self) -> None:
        self.state["active_leg_index"] = 0
        self._resume_sell("海角城")
        self.assertTrue(self._action("ManualTwoCityBusinessAfterSellAction"))
        self._open_buy_page("海角城")

        self.assertEqual(self.state["completed_rounds"], 1)
        self.assertEqual(self.state["active_leg_index"], 1)
        self.assertEqual(self.state["trade_phase"], "buy")
        self.assertEqual(self.trade["_manual_two_city_leg_run_marker"](), "1|1|海角城|岚心城")

    def test_pre_buy_cleanup_keeps_current_buy_leg_and_book_usage(self) -> None:
        self.state.update(active_leg_index=0, pre_buy_cleanup=True)
        self._resume_sell("岚心城")
        self.assertEqual(self.state["active_leg_index"], 0)
        self.assertTrue(self._action("ManualTwoCityBusinessAfterSellAction"))
        self._open_buy_page("岚心城")

        self.assertEqual(self.state["completed_rounds"], 1)
        self.assertEqual(self.state["active_leg_index"], 0)
        self.assertEqual(self.state["trade_phase"], "buy")
        self.assertNotIn("pre_buy_cleanup", self.state)
        self.assertEqual(self.trade["_manual_two_city_leg_run_marker"](), self.old_marker)
        self.assertEqual(self.trade["_manual_two_city_buy_book_usage"](), self.old_usage)
        self.trade["_manual_two_city_click_ocr_text"].assert_called_once()

    def test_buy_and_startup_select_the_leg_that_buys_in_current_city(self) -> None:
        for phase in ("buy", ""):
            for expected_index in (0, 1):
                with self.subTest(phase=phase, expected_index=expected_index):
                    self.state.update(active_leg_index=1 - expected_index, trade_phase=phase)
                    self.state.pop("drink_resume_phase", None)
                    city = self.legs[expected_index]["buy_city"]
                    self.assertTrue(self._action("ManualTwoCityBusinessCurrentCityReadyAction", city))
                    self.assertEqual(self.state["active_leg_index"], expected_index)
                    self.assertEqual(self.state["current_city"], city)
                    self.assertEqual(self.state["completed_rounds"], 1)


if __name__ == "__main__":
    unittest.main()
