import base64
import json
import mimetypes
import re
import threading
from pathlib import Path

from lmstudio_client import LMStudioClient
from schemas import Message, ChatRequest
from skill_client import SkillClient
from terminal_display import TerminalDisplay


class SimpleAgent:
    def __init__(self, config, client, display=None):
        self.config = config
        self.client = client
        self.display = display or TerminalDisplay()
        self.history = []
        self.history_lock = threading.Lock()
        self.run_lock = threading.RLock()
        self.skill_client = SkillClient(base_url=config.skill_server_url)
        self.max_tool_steps = 20

    def _extract_think_blocks(self, text: str):
        if not text:
            return "", []

        think_blocks = [
            match.group(1).strip()
            for match in re.finditer(r"<think>(.*?)</think>", text, flags=re.DOTALL)
            if match.group(1).strip()
        ]
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned, think_blocks

    def _print_think_block(self, step: int, think_text: str):
        cleaned = " ".join(think_text.strip().split())
        if cleaned:
            self.display.think(step, cleaned)

    def _print_tool_message(self, step: int, message: str):
        cleaned = " ".join(message.strip().split())
        if cleaned:
            self.display.tool_note(step, cleaned)

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
        self.display.tool_call(step, self._summarize_tool_call(skill_call))

    def _print_tool_result(self, step: int, skill_result: dict):
        self.display.tool_result(step, self._summarize_tool_result(skill_result))

    def _append_history(self, user_input, response: str):
        with self.history_lock:
            self.history.append(Message(role="user", content=user_input))
            self.history.append(Message(role="assistant", content=response))
            if len(self.history) > 10:
                self.history = self.history[-10:]

    def append_assistant_event(self, content: str):
        with self.history_lock:
            self.history.append(Message(role="assistant", content=content))
            if len(self.history) > 10:
                self.history = self.history[-10:]

    def clear_history(self) -> int:
        with self.history_lock:
            cleared = len(self.history)
            self.history = []
            return cleared

    def history_size(self) -> int:
        with self.history_lock:
            return len(self.history)

    def set_show_think(self, enabled: bool):
        self.display.set_enabled("think", enabled)

    def think_enabled(self) -> bool:
        return self.display.is_enabled("think")

    def display_category_enabled(self, category: str) -> bool:
        return self.display.is_enabled(category)

    def refresh_runtime_clients(self):
        self.client = LMStudioClient(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )
        self.skill_client = SkillClient(base_url=self.config.skill_server_url)

    def _chat(self, messages, *, response_stream_callback=None) -> str:
        request = ChatRequest(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=getattr(self.config, "stream", False),
        )
        return self.client.chat(request, on_content_stream=response_stream_callback)

    def _build_base_messages(self, user_input):
        with self.history_lock:
            history_snapshot = list(self.history)
        return [
            Message(
                role="system",
                content=self.config.agent_layers.build_system_prompt(),
            ),
            *history_snapshot,
            Message(role="user", content=user_input),
        ]

    def _normalize_skill_call(self, payload, speech_text: str = ""):
        if not isinstance(payload, dict):
            return None

        skill = payload.get("skill")
        action = payload.get("action")
        args = payload.get("args", {})
        message = payload.get("message", "")

        if not isinstance(skill, str) or not isinstance(action, str):
            return None
        if not isinstance(args, dict):
            return None
        if not isinstance(message, str):
            message = ""

        speech_parts = []
        if message.strip():
            speech_parts.append(message.strip())
        if speech_text.strip():
            speech_parts.append(speech_text.strip())

        normalized = {
            "skill": skill,
            "action": action,
            "args": args,
        }
        if speech_parts:
            normalized["message"] = "\n".join(speech_parts)

        return normalized

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
            payload = None

        skill_call = self._normalize_skill_call(payload)
        if skill_call:
            return skill_call

        # Recover embedded tool JSON from replies that include reasoning text.
        decoder = json.JSONDecoder()
        matches = list(re.finditer(r'\{\s*"skill"\s*:', candidate))
        for match in reversed(matches):
            try:
                payload, end = decoder.raw_decode(candidate[match.start():])
            except json.JSONDecodeError:
                continue

            prefix = candidate[:match.start()].strip()
            suffix = candidate[match.start() + end:].strip()
            speech_parts = [part for part in [prefix, suffix] if part]
            speech_text = "\n".join(speech_parts)

            skill_call = self._normalize_skill_call(payload, speech_text=speech_text)
            if skill_call:
                return skill_call

        return None

    def _build_tool_result_message(self, skill_result: dict):
        result_json = json.dumps(skill_result, ensure_ascii=False)
        message_text = (
            "The skill server executed your JSON instruction.\n"
            f"Skill result JSON:\n{result_json}\n\n"
            "If more tool use is required, return exactly one JSON object."
            " Otherwise, answer the original user request."
        )
        image_parts = self._build_tool_result_image_parts(skill_result)
        if not image_parts:
            return Message(role="user", content=message_text)
        message_text += "\n\nA local image from the skill result is attached below."
        return Message(
            role="user",
            content=[{"type": "text", "text": message_text}, *image_parts],
        )

    def _image_file_to_data_url(self, image_path: str) -> str:
        resolved_path = Path(image_path).expanduser().resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"Image not found: {resolved_path}")

        mime_type, _ = mimetypes.guess_type(str(resolved_path))
        if not mime_type:
            mime_type = "application/octet-stream"

        encoded = base64.b64encode(resolved_path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _build_tool_result_image_parts(self, skill_result: dict):
        if not isinstance(skill_result, dict):
            return []
        if skill_result.get("skill") != "file-control":
            return []
        if skill_result.get("action") != "read":
            return []

        result = skill_result.get("result", {})
        if not isinstance(result, dict):
            return []
        data = result.get("data", {})
        if not isinstance(data, dict):
            return []
        if str(data.get("read_kind", "")).strip() != "image":
            return []

        local_path = str(data.get("local_path", "")).strip()
        if not local_path:
            return []

        try:
            data_url = self._image_file_to_data_url(local_path)
        except Exception:
            return []

        return [
            {
                "type": "image_url",
                "image_url": {
                    "url": data_url,
                },
            }
        ]

    def run(self, user_input, *, history_user_input=None, response_stream_callback=None) -> str:
        with self.run_lock:
            if hasattr(self.config, "reload_if_changed"):
                reloaded = bool(self.config.reload_if_changed())
                if reloaded:
                    self.refresh_runtime_clients()
                    self.display.system("Config, prompts, or skills changed. Runtime reloaded.")

            persisted_user_input = user_input if history_user_input is None else history_user_input
            messages = self._build_base_messages(user_input)
            last_response = ""

            for step in range(self.max_tool_steps + 1):
                try:
                    response = self._chat(
                        messages,
                        response_stream_callback=response_stream_callback,
                    )
                except Exception as e:
                    return f"[ERROR] {e}"

                cleaned_response, think_blocks = self._extract_think_blocks(response)
                for think_text in think_blocks:
                    self._print_think_block(step + 1, think_text)

                visible_response = cleaned_response.strip()
                if not visible_response and think_blocks:
                    visible_response = "[ERROR] Model returned thoughts without a final answer"
                elif not visible_response:
                    visible_response = response.strip()
                last_response = visible_response
                skill_call = self._parse_skill_call(cleaned_response or response)
                if not skill_call:
                    self._append_history(persisted_user_input, visible_response)
                    return visible_response

                if step >= self.max_tool_steps:
                    max_step_error = "[ERROR] Reached maximum tool steps before final answer"
                    self._append_history(persisted_user_input, max_step_error)
                    return max_step_error

                if skill_call.get("message"):
                    self._print_tool_message(step + 1, skill_call["message"])
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

            self._append_history(persisted_user_input, last_response)
            return last_response
