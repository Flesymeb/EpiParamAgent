from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _run_git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def get_git_info(repo_root: Optional[Path] = None) -> dict[str, Any]:
    repo_root = repo_root or find_repo_root()
    if not repo_root:
        return {"repo_root": None, "commit": None, "branch": None, "dirty": None}
    status = _run_git(repo_root, "status", "--porcelain")
    return {
        "repo_root": str(repo_root),
        "commit": _run_git(repo_root, "rev-parse", "HEAD") or None,
        "branch": _run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or None,
        "dirty": bool(status),
    }


def _file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _dir_digest(path: Path, limit: int = 2000) -> tuple[str, int, bool]:
    digest = hashlib.sha256()
    count = 0
    truncated = False
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = child.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(str(child.stat().st_size).encode("utf-8"))
        count += 1
        if count > limit:
            truncated = True
            break
    return digest.hexdigest(), min(count, limit), truncated


def describe_path(path_like: str | Path) -> dict[str, Any]:
    path = Path(path_like).resolve()
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if not path.exists():
        return info

    stat = path.stat()
    info["mtime_utc"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    if path.is_file():
        info["type"] = "file"
        info["size_bytes"] = stat.st_size
        info["sha256"] = _file_sha256(path)
        return info

    if path.is_dir():
        info["type"] = "dir"
        dir_hash, file_count, truncated = _dir_digest(path)
        info["file_count"] = file_count
        info["dir_digest"] = dir_hash
        info["dir_digest_truncated"] = truncated
        return info

    info["type"] = "other"
    return info


def summarize_paths(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    items = []
    for path in paths:
        if path is None or str(path).strip() == "":
            continue
        items.append(describe_path(path))
    return items


def redact_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def write_run_manifest(
    *,
    output_dir: Path,
    workflow: str,
    module: str,
    params: Optional[dict[str, Any]] = None,
    inputs: Optional[Iterable[str | Path]] = None,
    outputs: Optional[Iterable[str | Path]] = None,
    runtime: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = output_dir / f"run_manifest_{workflow}_{timestamp}.json"

    payload = {
        "timestamp_utc": utc_now_iso(),
        "workflow": workflow,
        "module": module,
        "cwd": str(Path.cwd()),
        "argv": sys.argv,
        "python_version": sys.version,
        "platform": platform.platform(),
        "git": get_git_info(repo_root=repo_root),
        "params": params or {},
        "inputs": summarize_paths(inputs or []),
        "outputs": summarize_paths(outputs or []),
        "runtime": runtime or {},
        "extra": extra or {},
    }

    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path
