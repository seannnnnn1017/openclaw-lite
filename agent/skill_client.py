import json
from urllib import request, error


class SkillClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def execute(self, skill: str, action: str, args: dict | None = None):
        payload = {
            "skill": skill,
            "action": action,
            "args": args or {},
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.base_url}/skills/execute",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Skill server HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Skill server unavailable: {exc.reason}") from exc
