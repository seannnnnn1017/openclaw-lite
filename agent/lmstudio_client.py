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

    def chat(self, request: ChatRequest) -> str:
        response = self.client.chat.completions.create(
            model=request.model,
            messages=request.to_dict()["messages"],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        message = response.choices[0].message
        content = self._coerce_text(getattr(message, "content", ""))

        reasoning = ""
        for key in ("reasoning_content", "reasoning", "thinking"):
            raw_value = self._get_message_extra(message, key)
            reasoning = self._coerce_text(raw_value).strip()
            if reasoning:
                break

        if reasoning:
            if content:
                return f"<think>{reasoning}</think>\n{content}"
            return f"<think>{reasoning}</think>"

        return content
