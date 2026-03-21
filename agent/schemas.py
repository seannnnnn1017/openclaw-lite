from dataclasses import dataclass
from typing import List, Dict


@dataclass
class AgentLayers:
    identity: str
    system_rules: str
    boundaries: str

    def build_system_prompt(self) -> str:
        return f"""
[IDENTITY]
{self.identity}

[SYSTEM RULES]
{self.system_rules}

[BOUNDARIES]
{self.boundaries}
""".strip()

    @staticmethod
    def from_json(data: Dict):
        return AgentLayers(
            identity=data["identity"],
            system_rules=data["system_rules"],
            boundaries=data["boundaries"]
        )


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ChatRequest:
    model: str
    messages: List[Message]
    temperature: float
    max_tokens: int

    def to_dict(self):
        return {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in self.messages
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }