"""Backward-compatibility shim. Run `python main.py` from the project root instead."""
import sys
from pathlib import Path

# Add project root (parent of agent/) to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from agent.app.application import AgentApplication


def main():
    config_path = _project_root / "agent" / "config" / "config.json"
    AgentApplication(config_path=config_path).run()


if __name__ == "__main__":
    main()
