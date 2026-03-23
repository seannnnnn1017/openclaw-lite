import json
import shutil
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
TEMP_DIR = SCRIPT_DIR / "temporary_data"
BACKUP_DIR = TEMP_DIR / "backups"
INDEX_FILE = TEMP_DIR / "file_ID.json"


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


def ensure_storage():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_FILE.exists():
        INDEX_FILE.write_text(
            json.dumps({"next_id": 1, "records": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_index() -> dict:
    ensure_storage()
    raw = INDEX_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return {"next_id": 1, "records": []}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"next_id": 1, "records": []}

    if not isinstance(data, dict):
        return {"next_id": 1, "records": []}

    records = data.get("records", [])
    next_id = data.get("next_id", 1)
    if not isinstance(records, list):
        records = []
    if not isinstance(next_id, int) or next_id < 1:
        next_id = 1

    return {
        "next_id": next_id,
        "records": records,
    }


def save_index(data: dict):
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_backup(action: str, path: str, full_path: str, reason: str) -> dict:
    index = load_index()
    backup_id = f"FILE-{index['next_id']:06d}"
    index["next_id"] += 1

    target_path = Path(full_path)
    existed_before = target_path.exists()
    backup_file = None

    if existed_before:
        backup_file = BACKUP_DIR / f"{backup_id}.bak"
        shutil.copy2(target_path, backup_file)

    entry = {
        "id": backup_id,
        "action": action,
        "path": path,
        "full_path": str(target_path),
        "reason": reason.strip() or "No reason provided",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "existed_before": existed_before,
        "backup_file": str(backup_file) if backup_file else None,
        "restored": False,
        "restore_count": 0,
    }

    index["records"].append(entry)
    save_index(index)
    return entry


def backup_metadata(entry: dict) -> dict:
    return {
        "backup_id": entry["id"],
        "backup_reason": entry["reason"],
        "existed_before": entry["existed_before"],
    }


def find_backup(backup_id: str):
    index = load_index()
    for entry in index["records"]:
        if entry.get("id") == backup_id:
            return index, entry
    return index, None


def restore_backup(backup_id: str):
    if not backup_id:
        return error("restore", "", "Missing backup_id")

    index, entry = find_backup(backup_id)
    if not entry:
        return error("restore", "", f"Backup ID not found: {backup_id}")

    full_path = Path(entry["full_path"])
    if entry.get("existed_before"):
        backup_file = entry.get("backup_file")
        if not backup_file or not Path(backup_file).exists():
            return error("restore", entry["path"], "Backup file missing")

        full_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_file, full_path)
    else:
        if full_path.exists():
            full_path.unlink()

    entry["restored"] = True
    entry["restore_count"] = int(entry.get("restore_count", 0)) + 1
    entry["restored_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_index(index)

    return ok(
        action="restore",
        path=entry["path"],
        message="File restored successfully",
        data={
            "backup_id": backup_id,
            "restored_action": entry["action"],
            "backup_reason": entry["reason"],
            "existed_before": entry["existed_before"],
            "restore_count": entry["restore_count"],
        },
    )


def ensure_file_target(action: str, path: str, full_path: str):
    if not path:
        return error(action, path, "Missing path")
    if Path(full_path).exists() and not Path(full_path).is_file():
        return error(action, path, "Only file paths are supported")
    return None


def run(
    action: str,
    path: str = "",
    content: str = "",
    target: str = "",
    new_text: str = "",
    occurrence: int = 1,
    reason: str = "",
    backup_id: str = "",
):
    try:
        if action == "restore":
            return restore_backup(backup_id)

        full_path = safe_path(path)
        target_error = ensure_file_target(action, path, full_path)
        if target_error:
            return target_error

        if action == "read":
            if not Path(full_path).exists():
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
            backup = create_backup(action, path, full_path, reason)
            write_text(full_path, content)
            return ok(
                action=action,
                path=path,
                message="File written successfully",
                data={
                    "written_chars": len(content),
                    **backup_metadata(backup),
                },
            )

        elif action == "append":
            backup = create_backup(action, path, full_path, reason)
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(content)
            return ok(
                action=action,
                path=path,
                message="Content appended successfully",
                data={
                    "appended_chars": len(content),
                    **backup_metadata(backup),
                },
            )

        elif action == "create":
            backup = create_backup(action, path, full_path, reason)
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            Path(full_path).touch(exist_ok=True)
            return ok(
                action=action,
                path=path,
                message="File created successfully",
                data=backup_metadata(backup),
            )

        elif action == "delete":
            if not Path(full_path).exists():
                return error(action, path, "File not found")

            backup = create_backup(action, path, full_path, reason)
            Path(full_path).unlink()
            return ok(
                action=action,
                path=path,
                message="File deleted successfully",
                data=backup_metadata(backup),
            )

        elif action == "replace_text":
            if not Path(full_path).exists():
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

            backup = create_backup(action, path, full_path, reason)
            write_text(full_path, updated)
            return ok(
                action=action,
                path=path,
                message="Text replaced successfully",
                data={
                    "target_occurrences": matches,
                    "replaced_count": replaced_count,
                    **backup_metadata(backup),
                },
            )

        elif action == "insert_after":
            if not Path(full_path).exists():
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

            backup = create_backup(action, path, full_path, reason)
            write_text(full_path, updated)
            return ok(
                action=action,
                path=path,
                message="Text inserted successfully",
                data={
                    "target_occurrences": matches,
                    **backup_metadata(backup),
                },
            )

        elif action == "insert_before":
            if not Path(full_path).exists():
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

            backup = create_backup(action, path, full_path, reason)
            write_text(full_path, updated)
            return ok(
                action=action,
                path=path,
                message="Text inserted successfully",
                data={
                    "target_occurrences": matches,
                    **backup_metadata(backup),
                },
            )

        else:
            return error(action, path, f"Unknown action: {action}")

    except Exception as e:
        return error(action, path, str(e))
