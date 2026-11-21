from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from agent.utils.action_helpers import ocr_roi, parse_action_param, tap_point
from agent.utils.input_guard import safe_screencap, sleep_with_stop
from maa_resonance.logic.story_skip import plan_story_skip_step

STORY_TOP_OCR_ROI = [0, 0, 1280, 90]
STORY_CENTER_OCR_ROI = [300, 220, 680, 340]
DEFAULT_CHOICE_INDEX = 0
EXIT_MISS_STREAK_LIMIT = 3


def _parse_action_param(argv: CustomAction.RunArg) -> dict[str, Any]:
    return parse_action_param(getattr(argv, "custom_action_param", None))


def _ocr_roi(context: Context, image: Any, node_name: str, roi: list[int]) -> list[dict[str, Any]]:
    return ocr_roi(context, image, node_name, roi)


def _tap_point(context: Context, node_name: str, x: int, y: int) -> bool:
    return tap_point(context, node_name, (int(x), int(y)))


@AgentServer.custom_action("story_skip_loop")
class StorySkipLoopAction(CustomAction):
    """Loop through dialogue choices and skip prompts until exiting story mode."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        params = _parse_action_param(argv)
        choice_index = int(params.get("choice_index", DEFAULT_CHOICE_INDEX) or 0)
        max_steps = int(params.get("max_steps", 120) or 120)
        exit_streak_limit = int(params.get("exit_streak_limit", EXIT_MISS_STREAK_LIMIT) or 3)

        miss_streak = 0
        prev_reason = ""
        for _ in range(max_steps):
            image = safe_screencap(context)
            if image is None:
                return False

            top_entries = _ocr_roi(context, image, f"{argv.node_name}TopOCR", STORY_TOP_OCR_ROI)
            center_entries: list[dict[str, Any]] = []
            if not top_entries or prev_reason == "click_skip":
                center_entries = _ocr_roi(
                    context, image, f"{argv.node_name}CenterOCR", STORY_CENTER_OCR_ROI
                )

            step = plan_story_skip_step(
                image,
                top_entries,
                center_entries,
                choice_index=choice_index,
            )
            action = step["action"]

            if action == "exit":
                miss_streak += 1
                if miss_streak >= exit_streak_limit:
                    print("[StorySkip] Exited story dialogue.", flush=True)
                    return True
                if not sleep_with_stop(context, 0.45):
                    return False
                continue

            miss_streak = 0
            prev_reason = str(step.get("reason") or "")
            if action == "click":
                px, py = step["point"]
                print(f"[StorySkip] {step['reason']} @ ({px}, {py})", flush=True)
                if not _tap_point(context, argv.node_name, int(px), int(py)):
                    return False
                if not sleep_with_stop(context, 0.55):
                    return False
            else:
                if not sleep_with_stop(context, 0.35):
                    return False

        print("[StorySkip] Reached max step limit.", flush=True)
        return True
