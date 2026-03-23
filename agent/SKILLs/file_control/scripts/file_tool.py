from pathlib import Path
import os

def safe_path(path: str) -> str:
    normalized = Path(path).expanduser()
    if not normalized.is_absolute():
        normalized = Path.cwd() / normalized
    return str(normalized.resolve())


def ok(action: str, path: str, data=None, message: str = ""):
    return {
        "status": "ok",
        "action": action,
        "path": path,
        "message": message,
        "data": data,
    }


def error(action: str, path: str, message: str):
    return {
        "status": "error",
        "action": action,
        "path": path,
        "message": message,
        "data": None,
    }


def run(action: str, path: str, content: str = ""):
    try:
        full_path = safe_path(path)

        if action == "read":
            if not os.path.exists(full_path):
                return error(action, path, "File not found")

            text = Path(full_path).read_text(encoding="utf-8")
            return ok(
                action=action,
                path=path,
                message="File read successfully",
                data={
                    "content": text,
                    "size": len(text)
                }
            )

        elif action == "write":
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            Path(full_path).write_text(content, encoding="utf-8")
            return ok(
                action=action,
                path=path,
                message="File written successfully",
                data={
                    "written_chars": len(content)
                }
            )

        elif action == "append":
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(content)
            return ok(
                action=action,
                path=path,
                message="Content appended successfully",
                data={
                    "appended_chars": len(content)
                }
            )

        elif action == "create":
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            Path(full_path).touch(exist_ok=True)
            return ok(
                action=action,
                path=path,
                message="File created successfully",
                data=None
            )

        elif action == "delete":
            if not os.path.exists(full_path):
                return error(action, path, "File not found")

            os.remove(full_path)
            return ok(
                action=action,
                path=path,
                message="File deleted successfully",
                data=None
            )

        else:
            return error(action, path, f"Unknown action: {action}")

    except Exception as e:
        return error(action, path, str(e))
