from pathlib import Path

from config_loader import Config
from lmstudio_client import LMStudioClient
from agent import SimpleAgent


def main():
    config_path = Path(__file__).resolve().parent / "config" / "config.json"
    config = Config(str(config_path))
    client = LMStudioClient(base_url=config.base_url, api_key=config.api_key)
    agent = SimpleAgent(config=config, client=client)

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break

        try:
            reply = agent.run(user_input)
            print(f"\nAgent: {reply}\n")
        except Exception as e:
            print(f"\n[ERROR] {e}\n")


if __name__ == "__main__":
    main()
