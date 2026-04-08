from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse


class LMStudioModelManagerError(RuntimeError):
    pass


def _coerce_int(value, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_rest_base_url(base_url: str) -> str:
    parsed = urlparse(str(base_url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise LMStudioModelManagerError(f"Invalid LM Studio base URL: {base_url!r}")

    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    api_path = f"{path}/api/v1" if path else "/api/v1"
    return urlunparse((parsed.scheme, parsed.netloc, api_path, "", "", ""))


class LMStudioModelManager:
    def __init__(self, *, base_url: str, api_key: str = "", timeout_seconds: float = 15.0):
        self.base_url = str(base_url or "").strip()
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = max(1.0, float(timeout_seconds or 15.0))
        self.rest_base_url = _build_rest_base_url(self.base_url)

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key and self.api_key.casefold() != "lm-studio":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout_seconds: float | None = None,
    ):
        url = f"{self.rest_base_url}{path}"
        headers = self._build_headers()
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(
            url=url,
            data=data,
            headers=headers,
            method=str(method or "GET").upper(),
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds or self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace").strip()
            message = f"LM Studio API {exc.code} for {path}"
            if error_body:
                message += f": {error_body}"
            raise LMStudioModelManagerError(message) from exc
        except urllib.error.URLError as exc:
            raise LMStudioModelManagerError(
                f"Cannot reach LM Studio at {self.rest_base_url}: {exc.reason}"
            ) from exc

        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LMStudioModelManagerError(
                f"LM Studio returned non-JSON for {path}: {body[:200]}"
            ) from exc

    def list_models(self) -> list[dict]:
        payload = self._request_json(method="GET", path="/models", timeout_seconds=min(self.timeout_seconds, 15.0))
        models = payload.get("models", [])
        if not isinstance(models, list):
            raise LMStudioModelManagerError("LM Studio returned an invalid model list payload")
        return [model for model in models if isinstance(model, dict)]

    def unload_instance(self, instance_id: str) -> dict:
        cleaned_instance_id = str(instance_id or "").strip()
        if not cleaned_instance_id:
            raise LMStudioModelManagerError("Missing LM Studio instance_id to unload")
        return self._request_json(
            method="POST",
            path="/models/unload",
            payload={"instance_id": cleaned_instance_id},
            timeout_seconds=self.timeout_seconds,
        )

    def load_model(self, *, model_key: str, context_window: int) -> dict:
        cleaned_model_key = str(model_key or "").strip()
        if not cleaned_model_key:
            raise LMStudioModelManagerError("Missing LM Studio model key to load")
        return self._request_json(
            method="POST",
            path="/models/load",
            payload={
                "model": cleaned_model_key,
                "context_length": int(context_window),
                "echo_load_config": True,
            },
            timeout_seconds=max(self.timeout_seconds, 300.0),
        )

    def ensure_model(self, *, model_name: str, context_window: int, load_model_key: str | None = None) -> dict:
        desired_model_name = str(model_name or "").strip()
        desired_context = _coerce_int(context_window, default=0)
        effective_load_key = str(load_model_key or desired_model_name).strip()

        if not desired_model_name:
            return {"status": "error", "message": "LLM model name is empty"}
        if desired_context <= 0:
            return {
                "status": "skipped",
                "message": "LM Studio model auto-management is disabled because context_window <= 0",
                "model": desired_model_name,
            }
        if not effective_load_key:
            return {"status": "error", "message": "LM Studio model load key is empty"}

        models = self.list_models()
        target_model = next((item for item in models if str(item.get("key", "")).strip() == effective_load_key), None)

        if target_model is None:
            target_model = next(
                (
                    item
                    for item in models
                    if any(
                        str(instance.get("id", "")).strip() == desired_model_name
                        for instance in item.get("loaded_instances", [])
                        if isinstance(instance, dict)
                    )
                ),
                None,
            )
            if target_model is not None:
                effective_load_key = str(target_model.get("key", "")).strip() or effective_load_key

        if target_model is None:
            return {
                "status": "error",
                "message": (
                    f"LM Studio model `{effective_load_key}` is not available on this machine. "
                    "Download it in LM Studio first or update `llm.model` / `llm.model_load_key`."
                ),
                "model": desired_model_name,
                "load_model_key": effective_load_key,
            }

        max_context = _coerce_int(target_model.get("max_context_length"), default=0)
        if max_context > 0 and desired_context > max_context:
            return {
                "status": "error",
                "message": (
                    f"Requested context_window={desired_context} exceeds LM Studio model "
                    f"`{effective_load_key}` max_context_length={max_context}."
                ),
                "model": desired_model_name,
                "load_model_key": effective_load_key,
                "max_context_length": max_context,
            }

        loaded_instances = [
            instance
            for instance in target_model.get("loaded_instances", [])
            if isinstance(instance, dict)
        ]
        for instance in loaded_instances:
            instance_id = str(instance.get("id", "")).strip()
            instance_context = _coerce_int(
                (instance.get("config") or {}).get("context_length"),
                default=0,
            )
            if instance_id == desired_model_name and instance_context == desired_context:
                return {
                    "status": "ok",
                    "message": (
                        f"LM Studio model `{instance_id}` already loaded with context_window={desired_context}."
                    ),
                    "model": desired_model_name,
                    "load_model_key": effective_load_key,
                    "instance_id": instance_id,
                    "context_window": desired_context,
                    "changed": False,
                }

        if desired_model_name != effective_load_key:
            return {
                "status": "error",
                "message": (
                    f"LM Studio can auto-load `{effective_load_key}`, but this config requests model "
                    f"`{desired_model_name}`. Automatic reload currently requires `llm.model` to match "
                    "`llm.model_load_key`."
                ),
                "model": desired_model_name,
                "load_model_key": effective_load_key,
            }

        unloaded_instance_ids: list[str] = []
        for instance in loaded_instances:
            instance_id = str(instance.get("id", "")).strip()
            if not instance_id:
                continue
            self.unload_instance(instance_id)
            unloaded_instance_ids.append(instance_id)

        load_response = self.load_model(
            model_key=effective_load_key,
            context_window=desired_context,
        )
        instance_id = str(load_response.get("instance_id", "")).strip() or effective_load_key
        actual_context = _coerce_int(
            (load_response.get("load_config") or {}).get("context_length"),
            default=desired_context,
        )
        if actual_context != desired_context:
            return {
                "status": "error",
                "message": (
                    f"LM Studio loaded `{instance_id}` with context_window={actual_context}, "
                    f"not the requested {desired_context}."
                ),
                "model": desired_model_name,
                "load_model_key": effective_load_key,
                "instance_id": instance_id,
                "context_window": actual_context,
            }

        return {
            "status": "ok",
            "message": (
                f"LM Studio loaded `{instance_id}` with context_window={actual_context}."
            ),
            "model": desired_model_name,
            "load_model_key": effective_load_key,
            "instance_id": instance_id,
            "context_window": actual_context,
            "changed": True,
            "unloaded_instance_ids": unloaded_instance_ids,
        }
