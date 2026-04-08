from pathlib import Path


def run(action: str, **kwargs):
    if action == "info":
        cwd = Path.cwd().resolve()
        return {
            "status": "ok",
            "action": "info",
            "message": "Workspace path context resolved.",
            "data": {
                "cwd": str(cwd),
                "project_root": str(cwd),
                "agent_dir": str(cwd / "agent"),
                "memories_dir": str(cwd / "agent" / "data" / "memories"),
                "skills_dir": str(cwd / "agent" / "SKILLs"),
            },
        }

    return {
        "status": "error",
        "action": action,
        "message": f"Unknown action: {action!r}. Supported actions: info",
        "data": None,
    }
