from openai import OpenAI
from schemas import ChatRequest


class LMStudioClient:
    def __init__(self, base_url: str, api_key: str):
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    def chat(self, request: ChatRequest) -> str:
        response = self.client.chat.completions.create(
            model=request.model,
            messages=request.to_dict()["messages"],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return response.choices[0].message.content
