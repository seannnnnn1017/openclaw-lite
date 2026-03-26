from pathlib import Path

try:
    from app.application import AgentApplication
except ModuleNotFoundError:
    from agent.app.application import AgentApplication


def main():
    config_path = Path(__file__).resolve().parent / "config" / "config.json"
    AgentApplication(config_path=config_path).run()


if __name__ == "__main__":
    main()
