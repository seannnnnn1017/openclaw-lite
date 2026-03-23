from pathlib import Path

from config_loader import Config
from lmstudio_client import LMStudioClient
from agent import SimpleAgent
from system_doc_generator import generate_system_architecture


def main():
    config_path = Path(__file__).resolve().parent / "config" / "config.json"
    config = Config(str(config_path))
    architecture_path = generate_system_architecture(config)
    print(f"[SYSTEM DOC GENERATED] {architecture_path}")
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
