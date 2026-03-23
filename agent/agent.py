import json

from schemas import Message, ChatRequest
from skill_client import SkillClient


class SimpleAgent:
    def __init__(self, config, client):
        self.config = config
        self.client = client
        self.history = []
        self.skill_client = SkillClient(base_url=config.skill_server_url)

    def _append_history(self, user_input: str, response: str):
        self.history.append(Message(role="user", content=user_input))
        self.history.append(Message(role="assistant", content=response))

        if len(self.history) > 10:
            self.history = self.history[-10:]

    def _chat(self, messages) -> str:
        request = ChatRequest(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return self.client.chat(request)

    def _build_base_messages(self, user_input: str):
        return [
            Message(
                role="system",
                content=self.config.agent_layers.build_system_prompt(),
            ),
            *self.history,
            Message(role="user", content=user_input),
        ]

    def _parse_skill_call(self, text: str):
        if not text:
            return None

        candidate = text.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            candidate = "\n".join(lines[1:-1]).strip()

        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        skill = payload.get("skill")
        action = payload.get("action")
        args = payload.get("args", {})

        if not isinstance(skill, str) or not isinstance(action, str):
            return None
        if not isinstance(args, dict):
            return None

        return {
            "skill": skill,
            "action": action,
            "args": args,
        }

    def _build_result_messages(self, user_input: str, skill_call: dict, skill_result: dict):
        result_json = json.dumps(skill_result, ensure_ascii=False)
        return [
            Message(
                role="system",
                content=self.config.agent_layers.build_system_prompt(),
            ),
            *self.history,
            Message(role="user", content=user_input),
            Message(role="assistant", content=json.dumps(skill_call, ensure_ascii=False)),
            Message(
                role="user",
                content=(
                    "The skill server executed your JSON instruction.\n"
                    f"Skill result JSON:\n{result_json}\n\n"
                    "Answer the original user request using this result."
                ),
            ),
        ]

    def run(self, user_input: str) -> str:
        if hasattr(self.config, "reload_if_changed"):
            self.config.reload_if_changed()
            self.skill_client = SkillClient(base_url=self.config.skill_server_url)

        base_messages = self._build_base_messages(user_input)

        try:
            first_response = self._chat(base_messages)
        except Exception as e:
            return f"[ERROR] {e}"

        skill_call = self._parse_skill_call(first_response)
        if not skill_call:
            self._append_history(user_input, first_response)
            return first_response

        try:
            skill_result = self.skill_client.execute(
                skill=skill_call["skill"],
                action=skill_call["action"],
                args=skill_call["args"],
            )
        except Exception as e:
            error_response = f"[ERROR] {e}"
            self._append_history(user_input, error_response)
            return error_response

        result_messages = self._build_result_messages(user_input, skill_call, skill_result)
        try:
            final_response = self._chat(result_messages)
        except Exception:
            final_response = json.dumps(skill_result, ensure_ascii=False)

        self._append_history(user_input, final_response)
        return final_response
