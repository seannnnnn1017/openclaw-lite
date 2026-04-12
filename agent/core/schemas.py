from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AgentLayers:
    identity: str
    system_rules: str
    memory_rules: str
    boundaries: str
    skills: List[Dict[str, str]] = field(default_factory=list)

    def build_system_prompt(self) -> str:
        prompt = f"""
[IDENTITY]
{self.identity}

[SYSTEM RULES]
{self.system_rules}

[MEMORY RULES]
{self.memory_rules}

[BOUNDARIES]
{self.boundaries}
""".strip()

        if not self.skills:
            return prompt

        routing_rules = """
[SKILL ROUTING]
- Enabled skills are listed below as compact manifests, not full `SKILL.md` bodies.
- When a skill is needed, prefer delegating with:
  {"skill":"<skill-name>","action":"__delegate__","args":{"task":"<single-skill objective>","context":{"key":"value"}}}
- If a user request clearly spans multiple skills, decompose it into ordered single-skill steps instead of delegating the whole job to one specialist.
- Never delegate an end-to-end cross-skill objective to one skill just because it mentions a final destination like Notion.
- For local-file-to-Notion work, gather the exact local content first with `file-control`, then hand the prepared content to `notion-basic` for the Notion write phase.
- Put the delegated objective in `args.task`.
- Put concrete ids, urls, paths, constraints, dates, and output requirements in `args.context`.
- Use a direct skill action only when the exact action and required arguments are obvious from the manifest.
- Never emit more than one JSON object in a single reply.
""".strip()

        skill_sections = []
        for skill in self.skills:
            manifest = skill.get("manifest") or {}
            skill_text = str(manifest.get("text", "")).strip()
            if not skill_text:
                continue
            skill_sections.append(skill_text)

        if not skill_sections:
            return prompt

        return f"{prompt}\n\n{routing_rules}\n\n[AVAILABLE SKILL MANIFESTS]\n" + "\n\n".join(
            skill_sections
        )

    def build_base_text(self) -> str:
        """Core prompt without skills — used for token breakdown."""
        return f"[IDENTITY]\n{self.identity}\n\n[SYSTEM RULES]\n{self.system_rules}\n\n[MEMORY RULES]\n{self.memory_rules}\n\n[BOUNDARIES]\n{self.boundaries}".strip()

    def build_skills_text(self) -> str:
        """Skills section only — used for token breakdown."""
        parts = []
        for skill in self.skills:
            t = str((skill.get("manifest") or {}).get("text", "")).strip()
            if t:
                parts.append(t)
        return "\n\n".join(parts)

    @staticmethod
    def from_json(data: Dict):
        return AgentLayers(
            identity=data["identity"],
            system_rules=data["system_rules"],
            memory_rules=data.get("memory_rules", ""),
            boundaries=data["boundaries"],
            skills=data.get("skills", []),
        )


@dataclass
class Message:
    role: str
    content: Any


@dataclass
class ChatRequest:
    model: str
    messages: List[Message]
    temperature: float
    max_tokens: int
    stream: bool = False

    def to_dict(self):
        return {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in self.messages
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": self.stream,
        }
