from schemas import Message, ChatRequest


class SimpleAgent:
    def __init__(self, config, client):
        self.config = config
        self.client = client
        self.history = []   # 短期記憶(每次對話重置)

    def build_messages(self, user_input: str):
        return [
            Message(
                role="system",
                content=self.config.agent_layers.build_system_prompt()
            ),
            *self.history,
            Message(role="user", content=user_input),
        ]

    def run(self, user_input: str) -> str:
        # config hot reload
        if hasattr(self.config, "reload_if_changed"):
            self.config.reload_if_changed()

        messages = self.build_messages(user_input)

        request = ChatRequest(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens
        )

        try:
            response = self.client.chat(request)
        except Exception as e:
            return f"[ERROR] {e}"

        # 更新記憶
        self.history.append(Message(role="user", content=user_input))
        self.history.append(Message(role="assistant", content=response))

        # 防止爆 context（簡單版）
        if len(self.history) > 10:
            self.history = self.history[-10:]

        return response