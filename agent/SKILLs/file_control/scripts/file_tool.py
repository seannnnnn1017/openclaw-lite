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


def read_text(full_path: str) -> str:
    return Path(full_path).read_text(encoding="utf-8")


def write_text(full_path: str, content: str):
    Path(full_path).parent.mkdir(parents=True, exist_ok=True)
    Path(full_path).write_text(content, encoding="utf-8")


def run(
    action: str,
    path: str,
    content: str = "",
    target: str = "",
    new_text: str = "",
    occurrence: int = 1,
):
    try:
        full_path = safe_path(path)

        if action == "read":
            if not os.path.exists(full_path):
                return error(action, path, "File not found")

            text = read_text(full_path)
            return ok(
                action=action,
                path=path,
                message="File read successfully",
                data={
                    "content": text,
                    "size": len(text),
                },
            )

        elif action == "write":
            write_text(full_path, content)
            return ok(
                action=action,
                path=path,
                message="File written successfully",
                data={"written_chars": len(content)},
            )

        elif action == "append":
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(content)
            return ok(
                action=action,
                path=path,
                message="Content appended successfully",
                data={"appended_chars": len(content)},
            )

        elif action == "create":
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            Path(full_path).touch(exist_ok=True)
            return ok(
                action=action,
                path=path,
                message="File created successfully",
                data=None,
            )

        elif action == "delete":
            if not os.path.exists(full_path):
                return error(action, path, "File not found")

            os.remove(full_path)
            return ok(
                action=action,
                path=path,
                message="File deleted successfully",
                data=None,
            )

        elif action == "replace_text":
            if not os.path.exists(full_path):
                return error(action, path, "File not found")

            if not target:
                return error(action, path, "Missing target text")

            text = read_text(full_path)
            matches = text.count(target)

            if matches == 0:
                return error(action, path, "Target text not found")

            if occurrence == 0:
                updated = text.replace(target, new_text)
                replaced_count = matches
            else:
                if occurrence < 1 or occurrence > matches:
                    return error(
                        action,
                        path,
                        f"Occurrence {occurrence} out of range (found {matches})",
                    )

                start = 0
                current = 0
                while True:
                    idx = text.find(target, start)
                    if idx == -1:
                        return error(action, path, "Target text not found")
                    current += 1
                    if current == occurrence:
                        updated = text[:idx] + new_text + text[idx + len(target):]
                        replaced_count = 1
                        break
                    start = idx + len(target)

            write_text(full_path, updated)
            return ok(
                action=action,
                path=path,
                message="Text replaced successfully",
                data={
                    "target_occurrences": matches,
                    "replaced_count": replaced_count,
                },
            )

        elif action == "insert_after":
            if not os.path.exists(full_path):
                return error(action, path, "File not found")

            if not target:
                return error(action, path, "Missing target text")

            text = read_text(full_path)
            matches = text.count(target)

            if matches == 0:
                return error(action, path, "Target text not found")

            if occurrence < 1 or occurrence > matches:
                return error(
                    action,
                    path,
                    f"Occurrence {occurrence} out of range (found {matches})",
                )

            start = 0
            current = 0
            while True:
                idx = text.find(target, start)
                if idx == -1:
                    return error(action, path, "Target text not found")
                current += 1
                if current == occurrence:
                    insert_pos = idx + len(target)
                    updated = text[:insert_pos] + new_text + text[insert_pos:]
                    break
                start = idx + len(target)

            write_text(full_path, updated)
            return ok(
                action=action,
                path=path,
                message="Text inserted successfully",
                data={"target_occurrences": matches},
            )

        elif action == "insert_before":
            if not os.path.exists(full_path):
                return error(action, path, "File not found")

            if not target:
                return error(action, path, "Missing target text")

            text = read_text(full_path)
            matches = text.count(target)

            if matches == 0:
                return error(action, path, "Target text not found")

            if occurrence < 1 or occurrence > matches:
                return error(
                    action,
                    path,
                    f"Occurrence {occurrence} out of range (found {matches})",
                )

            start = 0
            current = 0
            while True:
                idx = text.find(target, start)
                if idx == -1:
                    return error(action, path, "Target text not found")
                current += 1
                if current == occurrence:
                    updated = text[:idx] + new_text + text[idx:]
                    break
                start = idx + len(target)

            write_text(full_path, updated)
            return ok(
                action=action,
                path=path,
                message="Text inserted successfully",
                data={"target_occurrences": matches},
            )

        else:
            return error(action, path, f"Unknown action: {action}")

    except Exception as e:
        return error(action, path, str(e))