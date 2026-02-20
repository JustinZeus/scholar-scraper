from __future__ import annotations

from pathlib import Path

from app.services.domains.scholars.exceptions import ScholarServiceError


def _ensure_upload_root(upload_dir: str, *, create: bool) -> Path:
    root = Path(upload_dir).expanduser().resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_upload_path(upload_root: Path, relative_path: str) -> Path:
    candidate = (upload_root / relative_path).resolve()
    if upload_root != candidate and upload_root not in candidate.parents:
        raise ScholarServiceError("Invalid scholar image path.")
    return candidate


def _safe_remove_upload(upload_root: Path, relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        file_path = _resolve_upload_path(upload_root, relative_path)
    except ScholarServiceError:
        return

    try:
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    except OSError:
        return


def resolve_upload_file_path(*, upload_dir: str, relative_path: str) -> Path:
    root = _ensure_upload_root(upload_dir, create=False)
    return _resolve_upload_path(root, relative_path)
