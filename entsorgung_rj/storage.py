"""Local filesystem persistence for anonymous CLI client identities.

This module touches the local filesystem and is intended for CLI/local usage only;
Worker/serverless runtimes should manage identities via environment variables,
KV storage, or `entsorgung_rj.generate_identity()`.
"""

from __future__ import annotations

import json
from pathlib import Path

from entsorgung_rj.models import ClientIdentity, generate_identity

DEFAULT_STATE_PATH = Path.home() / ".config" / "entsorgung_rj" / "client.json"


def _read_cached_identity(state_path: Path) -> tuple[str, str] | None:
    if not state_path.exists():
        return None
    try:
        saved = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(saved, dict):
        return None

    uid = saved.get("anonymous_user_id")
    tok = saved.get("device_token")
    if isinstance(uid, str) and isinstance(tok, str):
        uid, tok = uid.strip(), tok.strip()
        if uid and tok:
            return uid, tok
    return None


def _write_cached_identity(state_path: Path, user_id: str, device_token: str) -> None:
    payload = {"anonymous_user_id": user_id, "device_token": device_token}
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Non-fatal if the config directory is not writable.
        pass


def load_or_create_identity(
    state_path: Path = DEFAULT_STATE_PATH,
    user_id_override: str | None = None,
    token_override: str | None = None,
) -> ClientIdentity:
    """Load a cached anonymous identity from disk, or generate and save a new one."""
    if user_id_override:
        return generate_identity(user_id_override, token_override, is_new=True)

    cached = _read_cached_identity(state_path)
    if cached is not None:
        saved_uid, saved_tok = cached
        tok = token_override.strip() if token_override else saved_tok
        return ClientIdentity(
            anonymous_user_id=saved_uid,
            device_token=tok,
            is_new=tok != saved_tok,
        )

    identity = generate_identity(device_token=token_override, is_new=True)
    _write_cached_identity(
        state_path,
        identity.anonymous_user_id,
        identity.device_token,
    )
    return identity
