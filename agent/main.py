import sys
import os
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.tasker import Tasker

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

AGENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import profile_prestige_action
from maa_resonance.logic import profile_parser


def print_runtime_diagnostics():
    numpy_status = "available" if profile_parser.np is not None else "missing"
    print(
        f"Agent runtime: python={sys.executable}, numpy={numpy_status}",
        flush=True,
    )


def main():
    log_dir = os.environ.get("MAA_RESONANCE_LOG_DIR", "./debug")
    Tasker.set_log_dir(log_dir)
    debug_enabled = os.environ.get("MAA_RESONANCE_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    if debug_enabled:
        Tasker.set_debug_mode(True)
    Tasker.set_reco_image_cache_limit(64)

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)
        
    socket_id = sys.argv[-1]

    if not AgentServer.start_up(socket_id):
        print(f"Failed to start MaaResonance Agent: {socket_id}", file=sys.stderr)
        sys.exit(2)

    print(f"Agent started: {socket_id}", flush=True)
    print_runtime_diagnostics()
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
