import ast
import base64
import json
import mimetypes
import re
from pathlib import Path

from schemas import ChatRequest, Message


class DelegatedSkillExecutor:
    def __init__(self, *, config, client, skill_client, display=None, max_tool_steps: int = 8):
        self.config = config
        self.client = client
        self.skill_client = skill_client
        self.display = display
        self.max_tool_steps = max_tool_steps

    def _chat(self, messages) -> str:
        request = ChatRequest(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=False,
        )
        return self.client.chat(request)

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

    def _print_tool_message(self, step: int, message: str):
        if not self.display:
            return
        cleaned = " ".join(str(message or "").strip().split())
        if cleaned:
            self.display.tool_note(step, f"[delegate] {cleaned}")

    def _print_tool_call(self, step: int, skill_call: dict):
        if not self.display:
            return
        args = skill_call.get("args", {})
        extra_keys = sorted(args.keys())
        summary = f"skill={skill_call.get('skill', '')} action={skill_call.get('action', '')}"
        if extra_keys:
            summary += f" args={','.join(extra_keys)}"
        self.display.tool_call(step, f"[delegate] {summary}")

    def _print_tool_result(self, step: int, skill_result: dict):
        if not self.display:
            return
        summary = (
            f"status={skill_result.get('status', '')} "
            f"skill={skill_result.get('skill', '')} "
            f"action={skill_result.get('action', '')}"
        )
        result = skill_result.get("result", {})
        if isinstance(result, dict):
            message = str(result.get("message", "")).strip()
            if message:
                summary += f' message="{message}"'
        if skill_result.get("error"):
            summary += f' error="{skill_result.get("error")}"'
        self.display.tool_result(step, f"[delegate] {summary}")

    def _normalize_skill_call(self, payload, *, allowed_skill: str, speech_text: str = ""):
        if not isinstance(payload, dict):
            return None

        skill = payload.get("skill")
        action = payload.get("action")
        args = payload.get("args", {})
        message = payload.get("message", "")

        if not isinstance(skill, str) or not isinstance(action, str):
            return None
        if skill.strip() != allowed_skill:
            return None
        if action.strip() == "__delegate__":
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
            "skill": skill.strip(),
            "action": action.strip(),
            "args": args,
        }
        if speech_parts:
            normalized["message"] = "\n".join(speech_parts)
        return normalized

    def _try_parse_structured_payload(self, candidate: str):
        cleaned = str(candidate or "").strip()
        if not cleaned:
            return None

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload

        try:
            payload = ast.literal_eval(cleaned)
        except (ValueError, SyntaxError):
            payload = None
        if isinstance(payload, dict):
            return payload

        return None

    def _find_matching_brace(self, text: str, start_index: int) -> int | None:
        depth = 0
        in_string = None
        escape = False

        for index in range(start_index, len(text)):
            char = text[index]
            if in_string is not None:
                if escape:
                    escape = False
                    continue
                if char == "\\":
                    escape = True
                    continue
                if char == in_string:
                    in_string = None
                continue

            if char in {'"', "'"}:
                in_string = char
                continue

            if char == "{":
                depth += 1
                continue

            if char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1

        return None

    def _iter_embedded_skill_payload_candidates(self, text: str):
        pattern = re.compile(r"\{\s*['\"]?skill['\"]?\s*:")
        for match in pattern.finditer(str(text or "")):
            start = match.start()
            end = self._find_matching_brace(text, start)
            if end is None:
                continue

            payload_text = text[start:end].strip()
            prefix = text[:start].strip()
            suffix = text[end:].strip()
            speech_parts = [part for part in (prefix, suffix) if part]
            yield payload_text, "\n".join(speech_parts)

    def _looks_like_tool_payload(self, text: str) -> bool:
        stripped = str(text or "").lstrip()
        if not stripped:
            return False

        head = stripped[:1000]
        if stripped.startswith("{") and "skill" in head and "action" in head:
            return True

        if stripped.startswith("```"):
            fence_body = stripped[3:].lstrip()
            if "skill" in fence_body[:1000] and "action" in fence_body[:1000]:
                return True

        return bool(
            re.search(r"\{\s*['\"]?skill['\"]?\s*:", head)
            and ("action" in head or "args" in head)
        )

    def _parse_skill_call(self, text: str, *, allowed_skill: str):
        if not text:
            return None

        candidate = text.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            candidate = "\n".join(lines[1:-1]).strip()

        payload = self._try_parse_structured_payload(candidate)
        skill_call = self._normalize_skill_call(payload, allowed_skill=allowed_skill)
        if skill_call:
            return skill_call

        for payload_text, speech_text in reversed(list(self._iter_embedded_skill_payload_candidates(candidate))):
            payload = self._try_parse_structured_payload(payload_text)
            skill_call = self._normalize_skill_call(
                payload,
                allowed_skill=allowed_skill,
                speech_text=speech_text,
            )
            if skill_call:
                return skill_call

        return None

    def _build_skill_format_repair_message(self, *, skill_name: str, invalid_response: str) -> str:
        return (
            f"You are the dedicated executor for `{skill_name}`.\n"
            "Return exactly one valid JSON object and nothing else.\n"
            f'Required schema: {{"skill":"{skill_name}","action":"<action-name>","args":{{...}}}}\n'
            "Rules:\n"
            f'- The `skill` field must always be `{skill_name}`.\n'
            "- `args` must be a JSON object.\n"
            "- Do not emit `__delegate__`.\n"
            "- Do not wrap the JSON in markdown fences.\n"
            "- Do not include explanations before or after the JSON.\n"
            f"Previous reply:\n{invalid_response}"
        )

    def _build_tool_result_message(self, skill_result: dict):
        result_json = json.dumps(skill_result, ensure_ascii=False)
        message_text = (
            "The skill server executed your JSON instruction.\n"
            f"Skill result JSON:\n{result_json}\n\n"
            "If more tool use is required, return exactly one JSON object."
            " Otherwise, answer the delegated task in natural language."
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

    def _build_system_prompt(self, skill: dict) -> str:
        skill_name = str(skill.get("name", "")).strip() or "unknown-skill"
        skill_content = str(skill.get("content", "")).strip()
        return f"""
[ROLE]
You are the dedicated executor for the single skill `{skill_name}`.
You do not have access to the user's full chat history.
You may use only this one skill and its instructions below.

[EXECUTION RULES]
- If tool use is needed, return exactly one JSON object and nothing else.
- The JSON schema is: {{"skill":"{skill_name}","action":"<action-name>","args":{{...}}}}
- The `skill` field must always stay `{skill_name}`.
- Never emit the special routing action `__delegate__`.
- Preserve the delegated task's constraints and requested output.
- If required information is missing, ask one concise clarifying question.
- After each tool result, either return another valid JSON object for `{skill_name}` or answer the delegated task in natural language.

[SKILL]
{skill_content}
""".strip()

    def _build_task_packet(self, *, skill_name: str, task: str, context: dict | None):
        packet = {
            "skill": skill_name,
            "task": str(task or "").strip(),
            "context": context or {},
        }
        return (
            "Delegated task packet:\n"
            f"{json.dumps(packet, ensure_ascii=False, indent=2)}\n\n"
            "Complete the delegated task using only the allowed skill."
        )

    def _success(self, *, skill_name: str, task: str, context: dict, final_response: str, tool_calls: int, last_tool_result):
        result = {
            "status": "ok",
            "action": "__delegate__",
            "path": skill_name,
            "message": "Delegated skill session completed",
            "data": {
                "delegated_skill": skill_name,
                "task": task,
                "context": context,
                "final_response": final_response,
                "tool_calls": tool_calls,
                "last_tool_result": last_tool_result,
            },
        }
        return {
            "status": "ok",
            "skill": skill_name,
            "action": "__delegate__",
            "result": result,
        }

    def _error(self, *, skill_name: str, message: str):
        return {
            "status": "error",
            "skill": skill_name,
            "action": "__delegate__",
            "error": message,
        }

    def run(self, *, skill: dict, task: str, context: dict | None = None):
        skill_name = str(skill.get("name", "")).strip()
        if not skill_name:
            return self._error(skill_name="unknown-skill", message="Delegated skill name is missing")

        normalized_context = context if isinstance(context, dict) else {"value": context}
        messages = [
            Message(role="system", content=self._build_system_prompt(skill)),
            Message(
                role="user",
                content=self._build_task_packet(
                    skill_name=skill_name,
                    task=task,
                    context=normalized_context,
                ),
            ),
        ]
        last_tool_result = None
        last_response = ""

        for step in range(self.max_tool_steps + 1):
            try:
                response = self._chat(messages)
            except Exception as exc:
                return self._error(skill_name=skill_name, message=str(exc))

            cleaned_response, _think_blocks = self._extract_think_blocks(response)
            visible_response = cleaned_response.strip() or response.strip()
            if not visible_response:
                visible_response = "[ERROR] Skill specialist returned an empty response"
            last_response = visible_response

            skill_call = self._parse_skill_call(cleaned_response or response, allowed_skill=skill_name)
            if not skill_call:
                if self._looks_like_tool_payload(cleaned_response or response):
                    if step >= self.max_tool_steps:
                        return self._error(
                            skill_name=skill_name,
                            message="Reached maximum tool steps while repairing delegated tool JSON",
                        )

                    malformed_response = cleaned_response or response
                    messages.append(Message(role="assistant", content=malformed_response))
                    messages.append(
                        Message(
                            role="user",
                            content=self._build_skill_format_repair_message(
                                skill_name=skill_name,
                                invalid_response=malformed_response,
                            ),
                        )
                    )
                    continue

                return self._success(
                    skill_name=skill_name,
                    task=task,
                    context=normalized_context,
                    final_response=visible_response,
                    tool_calls=step,
                    last_tool_result=last_tool_result,
                )

            if step >= self.max_tool_steps:
                return self._error(
                    skill_name=skill_name,
                    message="Reached maximum delegated tool steps before final answer",
                )

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
            except Exception as exc:
                skill_result = {
                    "status": "error",
                    "skill": skill_call["skill"],
                    "action": skill_call["action"],
                    "error": str(exc),
                }

            last_tool_result = skill_result
            self._print_tool_result(step + 1, skill_result)
            messages.append(self._build_tool_result_message(skill_result))

        return self._error(
            skill_name=skill_name,
            message=f"Delegated skill loop ended unexpectedly. Last response: {last_response}",
        )
