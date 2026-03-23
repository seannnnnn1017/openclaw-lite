from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class AgentLayers:
    identity: str
    system_rules: str
    boundaries: str
    skills: List[Dict[str, str]] = field(default_factory=list)

    def build_system_prompt(self) -> str:
        prompt = f"""
[IDENTITY]
{self.identity}

[SYSTEM RULES]
{self.system_rules}

[BOUNDARIES]
{self.boundaries}
""".strip()

        if not self.skills:
            return prompt

        skill_sections = []
        for skill in self.skills:
            skill_name = skill.get("name", "unknown-skill")
            skill_content = skill.get("content", "").strip()
            if not skill_content:
                continue
            skill_sections.append(f"[SKILL: {skill_name}]\n{skill_content}")

        if not skill_sections:
            return prompt

        return f"{prompt}\n\n[AVAILABLE SKILLS]\n" + "\n\n".join(skill_sections)

    @staticmethod
    def from_json(data: Dict):
        return AgentLayers(
            identity=data["identity"],
            system_rules=data["system_rules"],
            boundaries=data["boundaries"],
            skills=data.get("skills", []),
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
