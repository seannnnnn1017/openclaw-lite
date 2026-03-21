from dataclasses import dataclass, field
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


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ChatRequest:
    model: str
    messages: List[Message]
    temperature: float = 0.7
    max_tokens: int = 512

    def to_dict(self) -> Dict:
        return {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in self.messages
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }