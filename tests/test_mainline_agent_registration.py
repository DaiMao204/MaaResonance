import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class MainlineAgentRegistrationTest(unittest.TestCase):
    def test_daily_and_mainline_share_one_clarity_action(self):
        # Load the real entry point in a fresh interpreter so module caches from
        # other tests cannot hide a second import under a different name.
        probe = textwrap.dedent("""
            import os
            import sys
            from contextlib import ExitStack
            from unittest.mock import patch
            from maa.agent.agent_server import AgentServer

            sys.path.insert(0, os.getcwd())
            with ExitStack() as stack:
                actions = stack.enter_context(patch.object(AgentServer, "register_custom_action"))
                for name in ("register_custom_recognition", "_set_api_properties", "add_tasker_sink", "add_controller_sink"):
                    stack.enter_context(patch.object(AgentServer, name))
                import agent.main

            registered = [call.kwargs["action"] for call in actions.call_args_list
                          if call.kwargs["name"] == "clarity_recovery_action"]
            from agent.clarity_recovery_action import ClarityRecoveryAction
            assert [type(action) for action in registered] == [ClarityRecoveryAction], registered
        """)
        result = subprocess.run(
            [sys.executable, "-B", "-c", probe], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
