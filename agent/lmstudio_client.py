from openai import OpenAI

from schemas import ChatRequest


class LMStudioClient:
    def __init__(self, base_url: str, api_key: str):
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    def _coerce_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(str(text))
            return "\n".join(part for part in parts if part)
        return str(value)

    def _get_message_extra(self, message, key: str):
        if hasattr(message, key):
            return getattr(message, key)

        model_extra = getattr(message, "model_extra", None)
        if isinstance(model_extra, dict) and key in model_extra:
            return model_extra[key]

        if isinstance(message, dict):
            return message.get(key)

        return None

    def _combine_content_and_reasoning(self, *, content: str, reasoning: str) -> str:
        cleaned_content = str(content or "").strip()
        cleaned_reasoning = str(reasoning or "").strip()

        if cleaned_reasoning:
            if cleaned_content:
                return f"<think>{cleaned_reasoning}</think>\n{cleaned_content}"
            return f"<think>{cleaned_reasoning}</think>"

        return cleaned_content

    def _extract_reasoning_text(self, payload) -> str:
        for key in ("reasoning_content", "reasoning", "thinking"):
            raw_value = self._get_message_extra(payload, key)
            reasoning = self._coerce_text(raw_value).strip()
            if reasoning:
                return reasoning
        return ""

    def _notify_content_stream(self, callback, text: str, *, final: bool):
        if not callback:
            return

        try:
            callback(text, final=final)
        except TypeError:
            callback(text)
        except Exception:
            return

    def _collect_stream_text(self, stream, *, on_content_stream=None) -> str:
        content_parts = []
        reasoning_parts = []

        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if choices is None and isinstance(chunk, dict):
                choices = chunk.get("choices")
            if not choices:
                continue

            for choice in choices:
                delta = getattr(choice, "delta", None)
                if delta is None and isinstance(choice, dict):
                    delta = choice.get("delta")
                if delta is None:
                    continue

                content_piece = self._coerce_text(self._get_message_extra(delta, "content"))
                if content_piece:
                    content_parts.append(content_piece)
                    self._notify_content_stream(
                        on_content_stream,
                        "".join(content_parts),
                        final=False,
                    )

                reasoning_piece = self._extract_reasoning_text(delta)
                if reasoning_piece:
                    reasoning_parts.append(reasoning_piece)

        self._notify_content_stream(
            on_content_stream,
            "".join(content_parts),
            final=True,
        )
        return self._combine_content_and_reasoning(
            content="".join(content_parts),
            reasoning="".join(reasoning_parts),
        )

    def chat(self, request: ChatRequest, *, on_content_stream=None) -> str:
        create_kwargs = {
            "model": request.model,
            "messages": request.to_dict()["messages"],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": request.stream,
        }

        if request.stream:
            stream = self.client.chat.completions.create(**create_kwargs)
            return self._collect_stream_text(stream, on_content_stream=on_content_stream)

        response = self.client.chat.completions.create(**create_kwargs)
        message = response.choices[0].message
        content = self._coerce_text(getattr(message, "content", ""))
        reasoning = self._extract_reasoning_text(message)
        self._notify_content_stream(on_content_stream, content, final=True)
        return self._combine_content_and_reasoning(content=content, reasoning=reasoning)
