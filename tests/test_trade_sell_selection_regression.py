from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / "agent" / "profile_prestige_action.py"
ACTION = "ManualTwoCityBusinessSellPageReadyAction"
HELPER = "_manual_two_city_clear_top_all_sell_selection"


def _load_sell_actions(state: dict) -> dict:
    """Load production OCR and action code without Maa or a running game."""
    names = {
        ACTION,
        HELPER,
        "_box_xywh",
        "_collect_ocr_result_objects",
        "_ocr_texts_from_detail",
        "_ocr_entries_from_detail",
        "_ocr_texts",
        "_manual_two_city_screencap",
        "_manual_two_city_ocr_detail_from_image",
        "_manual_two_city_ocr_detail",
        "_manual_two_city_ocr_entries",
        "_manual_two_city_entry_matches",
        "_manual_two_city_texts_contain",
        "_manual_two_city_click",
    }
    constants = {"SELL_CART_SELECTED_ROI", "MANUAL_TWO_CITY_TASK_ENTRY"}
    namespace = {
        "CustomAction": object,
        "clean_text": lambda text: str(text or "").strip(),
        "time": SimpleNamespace(sleep=Mock()),
        "_manual_two_city_state": lambda: state,
        "_manual_two_city_active_leg": lambda: state["legs"][state["active_leg_index"]],
        "_append_user_log": Mock(),
        "_json_payload": Mock(),
    }
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"), filename=str(SOURCE))
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
        raise AssertionError(f"Production sell definitions missing: {sorted(missing)}")
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


def _result(text: str, box: list[int] | None = None) -> dict:
    entry = {"text": text}
    if box is not None:
        entry["box"] = box
    return entry


class SellPageUI:
    """Model the toggle shared by a partially selected and fully selected cart."""

    def __init__(
        self,
        selected: int = 0,
        *,
        clear_on_click: int | None = 1,
        empty_text: str = "全部卖出",
        frames: list[list[dict]] | None = None,
    ) -> None:
        self.selected = selected
        self.total = 6
        self.clear_on_click = clear_on_click
        self.empty_text = empty_text
        self.frames = frames
        self.captures: list[tuple[int, list[dict]]] = []
        self.probes: list[dict] = []
        self.clicks: list[tuple[int, int]] = []
        self.effects: list[str] = []
        self.cached_image = object()
        self.tasker = SimpleNamespace(controller=self)

    def post_screencap(self):
        index = len(self.captures)
        if self.frames is not None:
            entries = copy.deepcopy(self.frames[min(index, len(self.frames) - 1)])
        else:
            label = "全部取消" if self.selected else self.empty_text
            entries = [_result(label, [1166, 95, 60, 20])]
        image = (index, entries)
        self.captures.append(image)
        return SimpleNamespace(wait=lambda: SimpleNamespace(result=image))

    def run_recognition(self, name, image, override):
        node = override[name]
        self.probes.append({"image": image, **node})
        return SimpleNamespace(
            hit=any(text in entry["text"] for text in node["expected"] for entry in image[1]),
            all_results=image[1],
        )

    def post_click(self, x: int, y: int):
        self.clicks.append((x, y))
        if (x, y) != (1196, 105):
            self.effects.append("unexpected_click")
        elif self.selected:
            self.effects.append("cancel_selection")
            if self.clear_on_click is not None and len(self.clicks) >= self.clear_on_click:
                self.selected = 0
        else:
            self.effects.append("select_all")
            self.selected = self.total
        return SimpleNamespace(wait=lambda: None)


class TradeSellSelectionRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "legs": [
                {"buy_city": "岚心城", "sell_city": "海角城", "goods": ["岚心锦服"]},
                {"buy_city": "海角城", "sell_city": "岚心城", "goods": ["珍珠"]},
            ],
            "active_leg_index": 1,
            "completed_rounds": 3,
            "trade_phase": "sell",
            "drink_resume_phase": "sell",
            "buy_book_usage_by_leg": {
                "3|1|海角城|岚心城": {"attempted": True, "requested": 3, "used": 3},
            },
        }
        self.original_state = copy.deepcopy(self.state)
        self.trade = _load_sell_actions(self.state)

    def _run_action(self, ui: SellPageUI, *, old_text: str = "全部卖出") -> bool:
        argv = SimpleNamespace(reco_detail=SimpleNamespace(all_results=[_result(old_text)]))
        result = self.trade[ACTION]().run(ui, argv)
        self.assertEqual(self.state, self.original_state)
        return result

    def _assert_fresh_probes(self, ui: SellPageUI, count: int) -> None:
        self.assertEqual(len(ui.captures), count)
        self.assertEqual(len(ui.probes), count)
        for index, probe in enumerate(ui.probes):
            self.assertIs(probe["image"], ui.captures[index])
            self.assertEqual(probe["roi"], [860, 80, 400, 90])
            self.assertEqual(set(probe["expected"]), {"全部取消", "全部卖出", "全部出售"})

    def test_empty_cart_accepts_both_sell_all_labels_without_clicking(self) -> None:
        for label in ("全部卖出", "全部出售"):
            with self.subTest(label=label):
                ui = SellPageUI(empty_text=label)
                self.assertTrue(self._run_action(ui))
                self.assertEqual(ui.clicks, [])
                self._assert_fresh_probes(ui, 1)

    def test_partial_selection_is_cleared_then_verified_before_next_pipeline_step(self) -> None:
        ui = SellPageUI(selected=1)
        self.assertTrue(self._run_action(ui))
        self.assertEqual(ui.selected, 0)
        self.assertEqual(ui.clicks, [(1196, 105)])
        self.assertEqual(ui.effects, ["cancel_selection"])
        self._assert_fresh_probes(ui, 2)
        # The existing select-all step can now select every item instead of timing out.
        ui.post_click(1196, 105).wait()
        self.assertEqual(ui.selected, ui.total)

    def test_fully_selected_cart_is_also_cleared_and_reselected(self) -> None:
        ui = SellPageUI(selected=6)
        self.assertTrue(self._run_action(ui, old_text="全部取消"))
        self.assertEqual(ui.selected, 0)
        self.assertEqual(ui.effects, ["cancel_selection"])
        self._assert_fresh_probes(ui, 2)

    def test_cancel_retry_succeeds_only_after_fresh_empty_confirmation(self) -> None:
        ui = SellPageUI(selected=1, clear_on_click=2)
        self.assertTrue(self._run_action(ui))
        self.assertEqual(ui.selected, 0)
        self.assertEqual(len(ui.clicks), 2)
        self._assert_fresh_probes(ui, 3)

    def test_transition_frame_does_not_trigger_an_extra_toggle(self) -> None:
        ui = SellPageUI(
            selected=1,
            frames=[[_result("全部取消", [1166, 95, 60, 20])], [], [_result("全部出售")]],
        )
        self.assertTrue(self._run_action(ui))
        self.assertEqual(ui.effects, ["cancel_selection"])
        self._assert_fresh_probes(ui, 3)

    def test_unresponsive_cancel_is_bounded_and_returns_failure(self) -> None:
        ui = SellPageUI(selected=1, clear_on_click=None)
        self.assertFalse(self._run_action(ui))
        self.assertEqual(ui.selected, 1)
        self.assertEqual(ui.effects, ["cancel_selection"] * 4)
        self._assert_fresh_probes(ui, 5)
        self.assertEqual(self.trade["_json_payload"].call_args.args[1]["reason"], "stale_selection_clear_failed")

    def test_disappearing_cancel_without_empty_confirmation_is_not_success(self) -> None:
        ui = SellPageUI(selected=1, frames=[[_result("全部取消", [1166, 95, 60, 20])], []])
        self.assertFalse(self._run_action(ui))
        self.assertEqual(ui.effects, ["cancel_selection"])
        self._assert_fresh_probes(ui, 5)

    def test_unknown_screen_does_not_click_or_continue(self) -> None:
        ui = SellPageUI(frames=[[_result("交易所")]])
        self.assertFalse(self._run_action(ui))
        self.assertEqual(ui.clicks, [])
        self._assert_fresh_probes(ui, 5)

    def test_cancel_text_without_box_has_no_fixed_coordinate_fallback(self) -> None:
        ui = SellPageUI(selected=1, frames=[[_result("全部取消")]])
        self.assertFalse(self._run_action(ui))
        self.assertEqual(ui.clicks, [])
        self._assert_fresh_probes(ui, 5)

    def test_cancel_center_outside_roi_does_not_click(self) -> None:
        for box in ([820, 100, 20, 20], [1250, 95, 20, 20], [1166, 160, 60, 20]):
            with self.subTest(box=box):
                ui = SellPageUI(selected=1, frames=[[_result("全部取消", box)]])
                self.assertFalse(self._run_action(ui))
                self.assertEqual(ui.clicks, [])
                self._assert_fresh_probes(ui, 5)

    def test_invalid_cancel_center_does_not_click(self) -> None:
        for center in (None, "invalid", float("nan"), float("inf")):
            with self.subTest(center=center):
                ui = SellPageUI(selected=1)
                self.trade["_manual_two_city_ocr_entries"] = Mock(
                    return_value=(True, [{"text": "全部取消", "center_x": center, "center_y": 105}], ["全部取消"])
                )
                self.assertFalse(self._run_action(ui))
                self.assertEqual(ui.clicks, [])
                self.assertEqual(self.trade["_manual_two_city_ocr_entries"].call_count, 5)

    def test_cancel_takes_priority_when_ocr_also_contains_sell_all(self) -> None:
        ui = SellPageUI(
            selected=1,
            frames=[
                [_result("全部取消", [1166, 95, 60, 20]), _result("全部卖出")],
                [_result("全部卖出")],
            ],
        )
        self.assertTrue(self._run_action(ui))
        self.assertEqual(ui.effects, ["cancel_selection"])
        self._assert_fresh_probes(ui, 2)

    def test_action_obeys_failed_normalization_even_with_stale_ready_text(self) -> None:
        normalize = Mock(return_value=(False, ["全部取消"]))
        self.trade[HELPER] = normalize
        ui = SellPageUI(selected=1)
        self.assertFalse(self._run_action(ui, old_text="全部卖出"))
        normalize.assert_called_once()
        self.assertIs(normalize.call_args.args[0], ui)
        self.assertEqual(ui.clicks, [])

    def test_helper_preserves_observations_without_duplicate_texts(self) -> None:
        ui = SellPageUI(selected=1, clear_on_click=2)
        cleared, texts = self.trade[HELPER](ui, "SellRegression")
        self.assertTrue(cleared)
        self.assertEqual(texts, ["全部取消", "全部卖出"])
        self.assertEqual(self.state, self.original_state)


if __name__ == "__main__":
    unittest.main()
