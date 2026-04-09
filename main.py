import sys
from pathlib import Path

# Ensure project root is on sys.path so `from agent.X import Y` works
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.app.application import AgentApplication


def main():
    config_path = Path(__file__).resolve().parent / "agent" / "config" / "config.json"
    AgentApplication(config_path=config_path).run()


if __name__ == "__main__":
    main()
