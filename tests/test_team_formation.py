from types import SimpleNamespace
import unittest
from unittest.mock import patch

from maa_resonance.logic.team_formation import (
    DEFAULT_TEAM_ROLES,
    choose_next_quick_team_step,
    extract_quick_team_cards,
    is_main_formation_needs_update,
    match_formation_role,
    parse_target_roles,
    quick_team_page_signature,
    resolve_desired_roles,
)


class TeamFormationLogicTest(unittest.TestCase):
    def test_parse_target_roles_splits_and_deduplicates(self):
        parsed = parse_target_roles("小红帽, 静流·逐夏、那由他\n小红帽；星花")
        self.assertEqual(parsed, ["小红帽", "静流·逐夏", "那由他", "星花"])

    def test_match_formation_role_supports_custom_and_avoids_variant_confusion(self):
        targets = ["小红帽", "静流·逐夏", "那由他", "星花", "苍叶"]
        self.assertEqual(match_formation_role("小红帽", target_roles=targets), "小红帽")
        self.assertEqual(match_formation_role("静流·逐夏", target_roles=targets), "静流·逐夏")
        self.assertEqual(match_formation_role("静流逐夏", target_roles=targets), "静流·逐夏")
        self.assertEqual(match_formation_role("静流", target_roles=targets), "静流")

    def test_extract_quick_team_cards_from_live_ocr_boxes(self):
        # Sample boxes captured from 1280x720 quick-team screen
        entries = [
            {"text": "已上阵", "box": [80, 239, 38, 15]},
            {"text": "小红帽", "box": [122, 291, 51, 20]},
            {"text": "已上阵", "box": [257, 239, 40, 15]},
            {"text": "那由他", "box": [301, 291, 53, 20]},
            {"text": "已上阵", "box": [437, 239, 40, 15]},
            {"text": "静流·逐夏", "box": [454, 292, 76, 19]},
            {"text": "已上阵", "box": [614, 236, 46, 19]},
            {"text": "星花", "box": [674, 288, 42, 25]},
            {"text": "已上阵", "box": [796, 239, 42, 15]},
            {"text": "苍叶", "box": [854, 291, 38, 21]},
            {"text": "索玛", "box": [1034, 291, 38, 21]},
            {"text": "约书亚", "box": [1196, 289, 57, 24]},
            # Second row level text should be ignored as top-row role name
            {"text": "Lv.68", "box": [126, 567, 50, 25]},
        ]
        cards = extract_quick_team_cards(
            entries,
            target_roles=["小红帽", "静流·逐夏", "那由他", "星花", "苍叶"],
        )
        self.assertEqual(
            [(c["column"], c["role"], c["state"]) for c in cards],
            [
                (0, "小红帽", "selected"),
                (1, "那由他", "selected"),
                (2, "静流·逐夏", "selected"),
                (3, "星花", "selected"),
                (4, "苍叶", "selected"),
                (5, "索玛", "unselected"),
                (6, "约书亚", "unselected"),
            ],
        )

    def test_extract_quick_team_cards_detects_story_locked(self):
        entries = [
            {"text": "剧情", "box": [75, 225, 48, 20]},
            {"text": "伊卡菈", "box": [122, 291, 51, 20]},
            {"text": "已上阵", "box": [257, 239, 40, 15]},
            {"text": "小红帽", "box": [301, 291, 51, 20]},
        ]
        cards = extract_quick_team_cards(entries, target_roles=["小红帽", "静流·逐夏"])
        self.assertEqual(cards[0]["state"], "story_locked")
        self.assertEqual(cards[1]["state"], "selected")

    def test_resolve_desired_roles_respects_story_locks(self):
        desired = resolve_desired_roles(
            ["小红帽", "静流·逐夏", "那由他", "星花", "苍叶"],
            story_locked_roles=["伊卡菈"],
            max_team_size=5,
        )
        self.assertEqual(desired, ["伊卡菈", "小红帽", "静流·逐夏", "那由他", "星花"])

    def test_choose_next_step_deselects_unwanted_then_selects_and_confirms(self):
        targets = ["小红帽", "静流·逐夏", "那由他", "星花", "苍叶"]
        cards = [
            {"column": 0, "role": "伊卡菈", "state": "story_locked", "center": (100, 205)},
            {"column": 1, "role": "索玛", "state": "selected", "center": (279, 205)},
            {"column": 2, "role": "小红帽", "state": "unselected", "center": (459, 205)},
            {"column": 3, "role": "静流·逐夏", "state": "selected", "center": (639, 205)},
            {"column": 4, "role": "那由他", "state": "selected", "center": (819, 205)},
            {"column": 5, "role": "星花", "state": "selected", "center": (998, 205)},
        ]
        step1 = choose_next_quick_team_step(cards, targets)
        self.assertEqual(step1["action"], "click")
        self.assertEqual(step1["reason"], "deselect_unwanted")
        self.assertEqual(step1["role"], "索玛")

        # After deselecting 索玛, select 小红帽
        cards[1]["state"] = "unselected"
        step2 = choose_next_quick_team_step(cards, targets, known_story_roles={"伊卡菈"})
        self.assertEqual(step2["action"], "click")
        self.assertEqual(step2["reason"], "select_target")
        self.assertEqual(step2["role"], "小红帽")

        # After selecting 小红帽, all desired roles are active -> confirm
        cards[2]["state"] = "selected"
        step3 = choose_next_quick_team_step(cards, targets, known_story_roles={"伊卡菈"})
        self.assertEqual(step3["action"], "confirm")

    def test_choose_next_step_scrolls_when_full_with_offscreen_unwanted(self):
        targets = ["小红帽", "静流·逐夏", "那由他", "星花", "苍叶"]
        cards = [
            {"column": 0, "role": "小红帽", "state": "unselected", "center": (100, 205)},
            {"column": 1, "role": "索玛", "state": "unselected", "center": (279, 205)},
        ]
        step = choose_next_quick_team_step(
            cards,
            targets,
            confirmed_selected={"伊尔", "苏恩", "卡莱雅", "霖", "冯·里奈"},
        )
        self.assertEqual(step["action"], "scroll")
        self.assertTrue(quick_team_page_signature(cards))

    def test_is_main_formation_needs_update_avoids_reentry_loop(self):
        targets = ["小红帽", "静流·逐夏", "那由他", "星花", "苍叶"]
        full_names = [
            {"text": "小红帽"},
            {"text": "那由他"},
            {"text": "静流·逐夏"},
            {"text": "星花"},
            {"text": "苍叶"},
        ]
        # Empty slot triggers update in both modes
        self.assertTrue(is_main_formation_needs_update([], [{"text": "添加"}], targets, strict_match=False))
        self.assertTrue(is_main_formation_needs_update([], [{"text": "EMPTY"}], targets, strict_match=True))

        # Full matching roster never re-enters quick team
        self.assertFalse(is_main_formation_needs_update(full_names, [], targets, strict_match=False))
        self.assertFalse(is_main_formation_needs_update(full_names, [], targets, strict_match=True))

        # Unmatched full roster triggers only in strict mode
        wrong_names = [{"text": "莉薇娅"}, {"text": "苏恩"}, {"text": "小红帽"}, {"text": "星花"}, {"text": "苍叶"}]
        self.assertFalse(is_main_formation_needs_update(wrong_names, [], targets, strict_match=False))
        self.assertTrue(is_main_formation_needs_update(wrong_names, [], targets, strict_match=True))

        # Story-locked lineup with 1 forced external character does not trigger endless re-entry
        story_names = [{"text": "伊卡菈"}, {"text": "小红帽"}, {"text": "静流·逐夏"}, {"text": "那由他"}, {"text": "星花"}]
        self.assertFalse(
            is_main_formation_needs_update(story_names, [], targets, strict_match=True, has_story_lock=True)
        )

    def test_empty_target_roles_never_modifies_existing_lineup(self):
        import agent.team_formation_action as tfa

        self.assertEqual(DEFAULT_TEAM_ROLES, ())
        self.assertFalse(is_main_formation_needs_update([], [{"text": "添加"}], [], strict_match=False))
        self.assertFalse(is_main_formation_needs_update([], [{"text": "EMPTY"}], [], strict_match=True))

        cards = [
            {"column": 0, "role": "索玛", "state": "selected", "center": (100, 205)},
            {"column": 1, "role": "莉薇娅", "state": "unselected", "center": (279, 205)},
        ]
        step = choose_next_quick_team_step(cards, [])
        self.assertEqual(step["action"], "confirm")
        self.assertEqual(step["reason"], "no_target_roles_configured")

        reco_ctx = SimpleNamespace(
            run_recognition=lambda *_a, **_kw: self.fail("should not run OCR when target_roles is empty")
        )
        analyze_result_cls = getattr(
            tfa.CustomRecognition,
            "AnalyzeResult",
            lambda box=None, detail=None: SimpleNamespace(box=box, detail=detail),
        )
        with patch.object(tfa.CustomRecognition, "AnalyzeResult", analyze_result_cls, create=True):
            reco_res = tfa.TeamFormationNeedsUpdateRecognition().analyze(
                reco_ctx,
                SimpleNamespace(node_name="TestEmpty", image="dummy", custom_recognition_param={"target_roles": ""}),
            )
        self.assertIsNone(reco_res.box)
        self.assertEqual(reco_res.detail.get("reason"), "empty_target_roles")

        action_ctx = SimpleNamespace(
            tasker=SimpleNamespace(stopping=False, controller=None),
            run_action=lambda *_a, **_kw: self.fail("should not click when target_roles is empty"),
        )
        ok = tfa.TeamFormationQuickSelectAction().run(
            action_ctx,
            SimpleNamespace(node_name="TestEmptySelect", custom_action_param={"target_roles": ""}),
        )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
