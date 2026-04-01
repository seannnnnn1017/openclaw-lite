import ast
import base64
import json
import mimetypes
import re
import threading
from pathlib import Path

try:
    from skill.auto_context import collect_auto_context_messages
    from skill.delegated_executor import DelegatedSkillExecutor
    from integrations.lmstudio import LMStudioClient
    from core.schemas import Message, ChatRequest
    from skill.client import SkillClient
    from utils.terminal_display import TerminalDisplay
    from core.token_estimator import summarize_prompt_and_history
    from storage.memory import LongTermMemoryManager
except ImportError:
    from agent.skill.auto_context import collect_auto_context_messages
    from agent.skill.delegated_executor import DelegatedSkillExecutor
    from agent.integrations.lmstudio import LMStudioClient
    from agent.core.schemas import Message, ChatRequest
    from agent.skill.client import SkillClient
    from agent.utils.terminal_display import TerminalDisplay
    from agent.core.token_estimator import summarize_prompt_and_history
    from agent.storage.memory import LongTermMemoryManager


class SimpleAgent:
    def __init__(self, config, client, display=None, debug_logger=None):
        self.config = config
        self.client = client
        self.display = display or TerminalDisplay()
        self.debug_logger = debug_logger
        self.history = []
        self.history_lock = threading.Lock()
        self.run_lock = threading.RLock()
        self.skill_client = SkillClient(base_url=config.skill_server_url)
        self.memory_manager = LongTermMemoryManager(
            config=config,
            client=client,
            display=self.display,
            debug_logger=debug_logger,
        )
        self.max_tool_steps = 20
        self._interrupt_queue: list[str] = []
        self._interrupt_lock = threading.Lock()

    def _log_debug(self, kind: str, **payload):
        if not self.debug_logger:
            return
        try:
            self.debug_logger.log_event(kind, **payload)
        except Exception:
            return

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

    def _summarize_tool_result(self, skill_result: dict, *, depth: int = 0) -> str:
        parts = [
            f"status={skill_result.get('status', '')}",
            f"skill={skill_result.get('skill', '')}",
            f"action={skill_result.get('action', '')}",
        ]

        result = skill_result.get("result", {})
        if isinstance(result, dict):
            path = result.get("path")
            message = result.get("message")
            data = result.get("data", {})

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
                if "tool_calls" in data:
                    parts.append(f"tool_calls={data['tool_calls']}")
                if depth < 1 and isinstance(data.get("last_tool_result"), dict):
                    nested_summary = self._summarize_tool_result(data["last_tool_result"], depth=depth + 1)
                    if nested_summary:
                        parts.append(f'last_tool="{nested_summary}"')
        elif "error" in skill_result:
            parts.append(f'error="{skill_result["error"]}"')

        return " ".join(parts)

    def _print_tool_call(self, step: int, skill_call: dict):
        self.display.tool_call(step, self._summarize_tool_call(skill_call))

    def _print_tool_result(self, step: int, skill_result: dict):
        self.display.tool_result(step, self._summarize_tool_result(skill_result))

    def _build_tool_history_entry(self, *, step: int, kind: str, payload: dict) -> str:
        history_event = {
            "type": f"tool_{str(kind or '').strip().lower()}",
            "step": step,
            "payload": payload if isinstance(payload, dict) else {"value": payload},
        }
        return json.dumps(history_event, ensure_ascii=False, separators=(",", ":"), default=str)

    def _append_history(self, user_input, response: str, *, assistant_events: list[str] | None = None):
        with self.history_lock:
            self.history.append(Message(role="user", content=user_input))
            cleaned_events = [str(event or "").strip() for event in (assistant_events or []) if str(event or "").strip()]
            assistant_content = str(response or "")
            if cleaned_events:
                assistant_content = (
                    "[TOOL HISTORY JSONL]\n"
                    + "\n".join(cleaned_events)
                    + "\n\n[ASSISTANT RESPONSE]\n"
                    + assistant_content
                )
            self.history.append(Message(role="assistant", content=assistant_content))
            if len(self.history) > 10:
                self.history = self.history[-10:]

    def append_assistant_event(self, content: str):
        with self.history_lock:
            self.history.append(Message(role="assistant", content=content))
            if len(self.history) > 10:
                self.history = self.history[-10:]

    def enqueue_interrupt(self, text: str) -> None:
        with self._interrupt_lock:
            self._interrupt_queue.append(str(text or "").strip())

    def _flush_interrupt_queue(self) -> list[str]:
        with self._interrupt_lock:
            pending, self._interrupt_queue = self._interrupt_queue, []
        return [t for t in pending if t]

    def clear_history(self) -> int:
        with self.history_lock:
            cleared = len(self.history)
            self.history = []
            return cleared

    def history_size(self) -> int:
        with self.history_lock:
            return len(self.history)

    def token_estimate_summary(self) -> dict:
        with self.history_lock:
            history_snapshot = list(self.history)
        return summarize_prompt_and_history(
            self.config.agent_layers.build_system_prompt(),
            history_snapshot,
        )

    def long_term_memory_summary(self) -> dict:
        return self.memory_manager.stats()

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
        self.memory_manager = LongTermMemoryManager(
            config=self.config,
            client=self.client,
            display=self.display,
            debug_logger=self.debug_logger,
        )

    def _get_skill_config(self, skill_name: str) -> dict | None:
        if hasattr(self.config, "get_skill"):
            return self.config.get_skill(skill_name)

        for skill in getattr(self.config, "skills", []):
            if str(skill.get("name", "")).strip() == str(skill_name or "").strip():
                return skill
        return None

    def _skill_prefers_delegation(self, skill_name: str) -> bool:
        skill = self._get_skill_config(skill_name)
        manifest = skill.get("manifest", {}) if isinstance(skill, dict) else {}
        return bool(manifest.get("delegation_preferred", False))

    def _skill_delegation_mode(self, skill_name: str) -> str:
        skill = self._get_skill_config(skill_name)
        manifest = skill.get("manifest", {}) if isinstance(skill, dict) else {}
        mode = str(manifest.get("delegation_mode", "")).strip()
        if mode:
            return mode
        return "prefer" if self._skill_prefers_delegation(skill_name) else "direct_ok"

    def _normalize_delegate_args(self, args: dict) -> tuple[str, dict]:
        if not isinstance(args, dict):
            return "Complete the delegated skill task.", {"raw_args": args}

        task = str(args.get("task", "")).strip() or "Complete the delegated skill task."
        context_value = args.get("context", {})
        if isinstance(context_value, dict):
            context = dict(context_value)
        elif context_value in ("", None):
            context = {}
        else:
            context = {"value": context_value}

        extra_args = {
            key: value
            for key, value in args.items()
            if key not in {"task", "context"}
        }
        if extra_args:
            context["delegation_args"] = extra_args
        return task, context

    def _append_auto_context_messages(
        self,
        messages: list[Message],
        *,
        user_input: str = "",
        skill_call: dict | None = None,
        executed_skills: set[str],
        debug_context: dict | None = None,
    ) -> set[str]:
        auto_messages, updated_executed = collect_auto_context_messages(
            self.config.skills,
            user_input=user_input,
            skill_call=skill_call,
            executed_skills=executed_skills,
        )
        for index, content in enumerate(auto_messages, start=1):
            messages.append(Message(role="user", content=content))
            self._log_debug(
                "auto_context",
                debug_context=dict(debug_context or {}),
                ordinal=index,
                content=content,
                skill_call=skill_call,
            )
        return updated_executed

    def _execute_delegated_skill(
        self,
        skill_call: dict,
        *,
        original_user_input: str = "",
        trigger_reason: str = "",
    ):
        skill_name = str(skill_call.get("skill", "")).strip()
        skill = self._get_skill_config(skill_name)
        if not skill:
            return {
                "status": "error",
                "skill": skill_name or "unknown-skill",
                "action": "__delegate__",
                "error": f"Unknown skill: {skill_name}",
            }

        action = str(skill_call.get("action", "")).strip()
        args = skill_call.get("args", {}) if isinstance(skill_call.get("args"), dict) else {}
        delegation_mode = self._skill_delegation_mode(skill_name)
        if action == "__delegate__":
            task, context = self._normalize_delegate_args(args)
        elif delegation_mode == "specialist_only":
            task = str(original_user_input or "").strip() or f"Handle the user's request using `{skill_name}`."
            context = {
                "original_user_input": str(original_user_input or "").strip(),
                "requested_action": action,
                "requested_args": args,
                "hinted_skill_call": skill_call,
                "hints_are_untrusted": True,
            }
            if trigger_reason:
                context["specialist_trigger"] = trigger_reason
        else:
            task = (
                f"Carry out the requested `{action}` action for skill `{skill_name}` "
                "using the provided arguments and recover gracefully if the first attempt fails."
            )
            context = {
                "requested_action": action,
                "requested_args": args,
            }

        executor = DelegatedSkillExecutor(
            config=self.config,
            client=self.client,
            skill_client=self.skill_client,
            display=self.display,
            debug_logger=self.debug_logger,
        )
        return executor.run(
            skill=skill,
            task=task,
            context=context,
            debug_context={
                "source": "delegate",
                "parent_skill_call": skill_call,
            },
        )

    def _skill_result_has_error(self, skill_result: dict) -> bool:
        if not isinstance(skill_result, dict):
            return True
        if str(skill_result.get("status", "")).strip().lower() == "error":
            return True
        result = skill_result.get("result", {})
        if isinstance(result, dict) and str(result.get("status", "")).strip().lower() == "error":
            return True
        return False

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
        messages = [
            Message(
                role="system",
                content=self.config.agent_layers.build_system_prompt(),
            ),
        ]
        memory_message = self.memory_manager.build_memory_message(user_input)
        if memory_message:
            messages.append(Message(role="system", content=memory_message))
        messages.extend(history_snapshot)
        messages.append(Message(role="user", content=user_input))
        return messages

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
            speech_parts = [part for part in [prefix, suffix] if part]
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

    def _build_skill_format_repair_message(self, invalid_response: str) -> str:
        return (
            "Your previous reply looks like an attempted skill call, but it was not a valid executable JSON object.\n"
            "Return exactly one valid JSON object and nothing else.\n"
            'Required schema: {"skill":"<skill-name>","action":"<action-name>","args":{...}}\n'
            "Rules:\n"
            "- Use double quotes for every key and string value.\n"
            "- `args` must be a JSON object.\n"
            "- Do not wrap the JSON in markdown fences.\n"
            "- Do not include explanations before or after the JSON.\n"
            f"Previous reply:\n{invalid_response}"
        )

    def _parse_skill_call(self, text: str):
        if not text:
            return None

        candidate = text.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            lines = candidate.splitlines()
            candidate = "\n".join(lines[1:-1]).strip()

        payload = self._try_parse_structured_payload(candidate)
        skill_call = self._normalize_skill_call(payload)
        if skill_call:
            return skill_call

        for payload_text, speech_text in reversed(
            list(self._iter_embedded_skill_payload_candidates(candidate))
        ):
            payload = self._try_parse_structured_payload(payload_text)
            skill_call = self._normalize_skill_call(payload, speech_text=speech_text)
            if skill_call:
                return skill_call

        return None

    def _build_tool_result_message(self, skill_result: dict):
        result_json = json.dumps(skill_result, ensure_ascii=False)
        if self._skill_result_has_error(skill_result):
            message_text = (
                "The skill server returned an error for your JSON instruction.\n"
                f"Skill result JSON:\n{result_json}\n\n"
                "If recovery is possible, return exactly one JSON object."
                " Otherwise, explain the failure clearly."
                " Do not claim the requested side effect succeeded unless a later tool result confirms success."
            )
        else:
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

    def run(self, user_input, *, history_user_input=None, response_stream_callback=None, debug_context=None) -> str:
        with self.run_lock:
            if hasattr(self.config, "reload_if_changed"):
                reloaded = bool(self.config.reload_if_changed())
                if reloaded:
                    self.refresh_runtime_clients()
                    self.display.system("Config, prompts, or skills changed. Runtime reloaded.")
                    self._log_debug("runtime_reload", debug_context=dict(debug_context or {}))

            persisted_user_input = user_input if history_user_input is None else history_user_input
            messages = self._build_base_messages(user_input)
            last_response = ""
            turn_history_events = []
            normalized_debug_context = dict(debug_context or {})
            self._log_debug(
                "user_input",
                debug_context=normalized_debug_context,
                user_input=user_input,
                history_user_input=history_user_input,
                persisted_user_input=persisted_user_input,
            )
            auto_context_executed: set[str] = set()
            auto_context_executed = self._append_auto_context_messages(
                messages,
                user_input=user_input,
                executed_skills=auto_context_executed,
                debug_context=normalized_debug_context,
            )

            for step in range(self.max_tool_steps + 1):
                try:
                    self.display.set_waiting("thinking")
                    response = self._chat(
                        messages,
                        response_stream_callback=response_stream_callback,
                    )
                except Exception as e:
                    self._log_debug(
                        "chat_error",
                        debug_context=normalized_debug_context,
                        step=step + 1,
                        error=str(e),
                    )
                    return f"[ERROR] {e}"

                cleaned_response, think_blocks = self._extract_think_blocks(response)
                self._log_debug(
                    "model_response",
                    debug_context=normalized_debug_context,
                    step=step + 1,
                    raw_response=response,
                    cleaned_response=cleaned_response,
                    think_blocks=think_blocks,
                )
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
                    if self._looks_like_tool_payload(cleaned_response or response):
                        if step >= self.max_tool_steps:
                            max_step_error = "[ERROR] Reached maximum tool steps while repairing malformed tool JSON"
                            self._append_history(
                                persisted_user_input,
                                max_step_error,
                                assistant_events=turn_history_events,
                            )
                            self._log_debug(
                                "tool_loop_error",
                                debug_context=normalized_debug_context,
                                step=step + 1,
                                error=max_step_error,
                            )
                            return max_step_error

                        self.display.tool_note(
                            step + 1,
                            "Detected malformed tool JSON. Requesting a corrected tool instruction.",
                        )
                        malformed_response = cleaned_response or response
                        self._log_debug(
                            "malformed_tool_payload",
                            debug_context=normalized_debug_context,
                            step=step + 1,
                            response=malformed_response,
                        )
                        messages.append(Message(role="assistant", content=malformed_response))
                        messages.append(
                            Message(
                                role="user",
                                content=self._build_skill_format_repair_message(malformed_response),
                            )
                        )
                        continue

                    self._append_history(
                        persisted_user_input,
                        visible_response,
                        assistant_events=turn_history_events,
                    )
                    self.memory_manager.remember_turn(
                        user_input=persisted_user_input,
                        assistant_response=visible_response,
                        debug_context=normalized_debug_context,
                    )
                    self._log_debug(
                        "final_response",
                        debug_context=normalized_debug_context,
                        step=step + 1,
                        response=visible_response,
                    )
                    return visible_response

                if step >= self.max_tool_steps:
                    max_step_error = "[ERROR] Reached maximum tool steps before final answer"
                    self._append_history(
                        persisted_user_input,
                        max_step_error,
                        assistant_events=turn_history_events,
                    )
                    self._log_debug(
                        "tool_loop_error",
                        debug_context=normalized_debug_context,
                        step=step + 1,
                        error=max_step_error,
                    )
                    return max_step_error

                updated_executed = self._append_auto_context_messages(
                    messages,
                    user_input=user_input,
                    skill_call=skill_call,
                    executed_skills=auto_context_executed,
                    debug_context=normalized_debug_context,
                )
                if updated_executed != auto_context_executed:
                    auto_context_executed = updated_executed
                    continue

                if skill_call.get("message"):
                    self._print_tool_message(step + 1, skill_call["message"])
                self._print_tool_call(step + 1, skill_call)
                self.display.set_waiting(f"tool  {skill_call['skill']} / {skill_call['action']}")
                turn_history_events.append(
                    self._build_tool_history_entry(
                        step=step + 1,
                        kind="CALL",
                        payload=skill_call,
                    )
                )
                self._log_debug(
                    "tool_call",
                    debug_context=normalized_debug_context,
                    step=step + 1,
                    skill_call=skill_call,
                )
                messages.append(Message(role="assistant", content=json.dumps(skill_call, ensure_ascii=False)))

                try:
                    if skill_call["action"] == "__delegate__":
                        skill_result = self._execute_delegated_skill(
                            skill_call,
                            original_user_input=user_input,
                            trigger_reason="explicit_delegate",
                        )
                    elif self._skill_delegation_mode(skill_call["skill"]) == "specialist_only":
                        self.display.tool_note(
                            step + 1,
                            "Routing this skill through the dedicated specialist before any live tool call.",
                        )
                        self._log_debug(
                            "specialist_reroute",
                            debug_context=normalized_debug_context,
                            step=step + 1,
                            skill_call=skill_call,
                            reason="specialist_only",
                        )
                        skill_result = self._execute_delegated_skill(
                            skill_call,
                            original_user_input=user_input,
                            trigger_reason="specialist_only",
                        )
                    else:
                        skill_result = self.skill_client.execute(
                            skill=skill_call["skill"],
                            action=skill_call["action"],
                            args=skill_call["args"],
                        )
                        if (
                            self._skill_result_has_error(skill_result)
                            and self._skill_prefers_delegation(skill_call["skill"])
                        ):
                            self.display.tool_note(
                                step + 1,
                                "Direct skill call failed. Retrying through the delegated specialist.",
                            )
                            skill_result = self._execute_delegated_skill(
                                skill_call,
                                original_user_input=user_input,
                                trigger_reason="direct_failure",
                            )
                except Exception as e:
                    skill_result = {
                        "status": "error",
                        "skill": skill_call["skill"],
                        "action": skill_call["action"],
                        "error": str(e),
                    }

                self._print_tool_result(step + 1, skill_result)
                turn_history_events.append(
                    self._build_tool_history_entry(
                        step=step + 1,
                        kind="RESULT",
                        payload=skill_result,
                    )
                )
                self._log_debug(
                    "tool_result",
                    debug_context=normalized_debug_context,
                    step=step + 1,
                    skill_result=skill_result,
                )
                messages.append(self._build_tool_result_message(skill_result))

                pending_interrupts = self._flush_interrupt_queue()
                for interrupt_text in pending_interrupts:
                    self.display.system(f"Injecting queued message: {interrupt_text[:80]}")
                    messages.append(Message(
                        role="user",
                        content=f"[User message received while you were executing a tool]\n{interrupt_text}",
                    ))

            self._append_history(
                persisted_user_input,
                last_response,
                assistant_events=turn_history_events,
            )
            self.memory_manager.remember_turn(
                user_input=persisted_user_input,
                assistant_response=last_response,
                debug_context=normalized_debug_context,
            )
            self._log_debug(
                "final_response",
                debug_context=normalized_debug_context,
                step=self.max_tool_steps + 1,
                response=last_response,
            )
            return last_response
