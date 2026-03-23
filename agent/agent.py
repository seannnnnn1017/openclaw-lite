import json

from schemas import Message, ChatRequest
from skill_client import SkillClient


class SimpleAgent:
    def __init__(self, config, client):
        self.config = config
        self.client = client
        self.history = []
        self.skill_client = SkillClient(base_url=config.skill_server_url)
        self.max_tool_steps = 6

    def _summarize_tool_call(self, skill_call: dict) -> str:
        args = skill_call.get("args", {})
        parts = [
            f"skill={skill_call.get('skill', '')}",
            f"action={skill_call.get('action', '')}",
        ]

        path = args.get("path")
        if path:
            parts.append(f"path={path}")

        if "content" in args:
            parts.append(f"content_chars={len(args.get('content', ''))}")
        if "target" in args:
            parts.append(f"target_chars={len(args.get('target', ''))}")
        if "new_text" in args:
            parts.append(f"new_text_chars={len(args.get('new_text', ''))}")
        if "occurrence" in args:
            parts.append(f"occurrence={args.get('occurrence')}")

        extra_keys = sorted(
            key
            for key in args.keys()
            if key not in {"path", "content", "target", "new_text", "occurrence"}
        )
        if extra_keys:
            parts.append(f"extra_args={','.join(extra_keys)}")

        return " ".join(parts)

    def _summarize_tool_result(self, skill_result: dict) -> str:
        parts = [
            f"status={skill_result.get('status', '')}",
            f"skill={skill_result.get('skill', '')}",
            f"action={skill_result.get('action', '')}",
        ]

        result = skill_result.get("result", {})
        if isinstance(result, dict):
            path = result.get("path")
            message = result.get("message")
            data = result.get("data")

            if path:
                parts.append(f"path={path}")
            if message:
                parts.append(f'message="{message}"')
            if isinstance(data, dict):
                if "size" in data:
                    parts.append(f"size={data['size']}")
                if "written_chars" in data:
                    parts.append(f"written_chars={data['written_chars']}")
                if "appended_chars" in data:
                    parts.append(f"appended_chars={data['appended_chars']}")
                if "target_occurrences" in data:
                    parts.append(f"target_occurrences={data['target_occurrences']}")
                if "replaced_count" in data:
                    parts.append(f"replaced_count={data['replaced_count']}")
        elif "error" in skill_result:
            parts.append(f'error="{skill_result["error"]}"')

        return " ".join(parts)

    def _print_tool_call(self, step: int, skill_call: dict):
        print(f"\n[TOOL CALL {step}] {self._summarize_tool_call(skill_call)}")

    def _print_tool_result(self, step: int, skill_result: dict):
        print(f"[TOOL RESULT {step}] {self._summarize_tool_result(skill_result)}\n")

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

    def _build_tool_result_message(self, skill_result: dict):
        result_json = json.dumps(skill_result, ensure_ascii=False)
        return Message(
            role="user",
            content=(
                "The skill server executed your JSON instruction.\n"
                f"Skill result JSON:\n{result_json}\n\n"
                "If more tool use is required, return exactly one JSON object."
                " Otherwise, answer the original user request."
            ),
        )

    def run(self, user_input: str) -> str:
        if hasattr(self.config, "reload_if_changed"):
            self.config.reload_if_changed()
            self.skill_client = SkillClient(base_url=self.config.skill_server_url)

        messages = self._build_base_messages(user_input)
        last_response = ""

        for step in range(self.max_tool_steps + 1):
            try:
                response = self._chat(messages)
            except Exception as e:
                return f"[ERROR] {e}"

            last_response = response
            skill_call = self._parse_skill_call(response)
            if not skill_call:
                self._append_history(user_input, response)
                return response

            if step >= self.max_tool_steps:
                max_step_error = "[ERROR] Reached maximum tool steps before final answer"
                self._append_history(user_input, max_step_error)
                return max_step_error

            self._print_tool_call(step + 1, skill_call)
            messages.append(Message(role="assistant", content=json.dumps(skill_call, ensure_ascii=False)))

            try:
                skill_result = self.skill_client.execute(
                    skill=skill_call["skill"],
                    action=skill_call["action"],
                    args=skill_call["args"],
                )
            except Exception as e:
                skill_result = {
                    "status": "error",
                    "skill": skill_call["skill"],
                    "action": skill_call["action"],
                    "error": str(e),
                }

            self._print_tool_result(step + 1, skill_result)
            messages.append(self._build_tool_result_message(skill_result))

        self._append_history(user_input, last_response)
        return last_response
