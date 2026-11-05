#!/usr/bin/env python3
"""Plan or apply an allowlisted, resumable same-filesystem project archive.

Default/--plan is read-only. --apply requires the completed core tar snapshot and
Git history bundle. No source content is deleted and existing targets are never
overwritten. The archive directory itself is never traversed as a move source.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

ARCHIVE_ID = "20261103_160112_pre_refactor"
ALLOWLIST = (
    "A_paper", "baselines", "data", "dev", "docs", "e2e", "evaluation",
    "external", "logs", "output", "paper_pool", "refine-logs", "scripts",
    "tmp", "webapp", "paper_pool_20260508.tar.zst", ".benchmarks", ".codegraph",
    ".playwright-cli", ".pytest_cache", ".ruff_cache", "__pycache__", ".env.local.bk",
)
KEEP = (
    ".git", ".venv", ".vscode", ".env.local", ".env.example", "metaagent",
    "configs", "tools", "tests", "dataset", "pyproject.toml", "uv.lock",
    "metaagent.sh", "readme.md", "OPTIMIZATION_PLAN.md", "archive",
)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def exists(path):
    return os.path.lexists(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sensitive(path):
    name = path.name.lower()
    return name.startswith(".env") or name in {"id_rsa", "id_ed25519", "credentials.json", "secrets.json"} or name.endswith((".pem", ".p12", ".pfx", ".key"))


def inventory(path):
    """lstat inventory; never follow symlinks or include file contents."""
    records = []

    def visit(current, relative):
        info = current.lstat()
        mode = info.st_mode
        kind = "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "symlink" if stat.S_ISLNK(mode) else "special"
        record = {"path": relative, "kind": kind, "mode": oct(stat.S_IMODE(mode)),
                  "size": info.st_size if kind != "directory" else 0,
                  "mtime_ns": info.st_mtime_ns, "inode": info.st_ino, "device": info.st_dev}
        if kind == "symlink":
            record["symlink_target_sha256"] = hashlib.sha256(os.fsencode(os.readlink(current))).hexdigest()
        elif kind == "file" and sensitive(current):
            record["sensitive_content_sha256"] = sha256(current)
        records.append(record)
        if kind == "directory":
            with os.scandir(current) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
            for entry in children:
                visit(Path(entry.path), entry.name if relative == "." else relative + "/" + entry.name)

    visit(path, ".")
    # chmod(.env.local.bk,0600) intentionally changes mode; all other structural,
    # size, timestamp and same-filesystem inode properties must remain identical.
    comparable = [{k: value for k, value in row.items() if k != "mode"} for row in records]
    digest = hashlib.sha256(json.dumps(comparable, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"files": sum(row["kind"] == "file" for row in records),
            "directories": sum(row["kind"] == "directory" for row in records),
            "symlinks": sum(row["kind"] == "symlink" for row in records),
            "special_files": sum(row["kind"] == "special" for row in records),
            "bytes": sum(row["size"] for row in records if row["kind"] == "file"),
            "inventory_sha256": digest}, records


def destination(name):
    return ("private/" if name == ".env.local.bk" else "legacy/") + name


def prerequisites(archive):
    result = {}
    for name in ("core_snapshot.tar.gz", "history.bundle"):
        path = archive / "state" / name
        result[name] = {"path": str(path), "present_nonempty": path.is_file() and not path.is_symlink() and path.stat().st_size > 0,
                        "bytes": path.stat().st_size if path.is_file() else 0}
    return result


def plan(root, archive):
    items = []
    for name in ALLOWLIST:
        source, target = root / name, archive / destination(name)
        source_present, target_present = exists(source), exists(target)
        status = "conflict" if source_present and target_present else "planned" if source_present else "already_moved" if target_present else "absent"
        item = {"source": name, "destination": destination(name), "status": status}
        inspect = source if source_present else target if target_present else None
        if inspect is not None:
            summary, _ = inventory(inspect)
            item.update(summary)
        items.append(item)
    return {"archive_id": ARCHIVE_ID, "root": str(root), "archive": str(archive), "mode": "plan_only_no_moves",
            "keep": list(KEEP), "prerequisites": prerequisites(archive), "items": items,
            "planned_files": sum(item.get("files", 0) for item in items if item["status"] == "planned"),
            "planned_bytes": sum(item.get("bytes", 0) for item in items if item["status"] == "planned"),
            "conflicts": [item["source"] for item in items if item["status"] == "conflict"],
            "dataset_subdirectories": "not moved by this script; separate dependency review required",
            "source_validation": "File-list/type/size/mtime/inode inventory; sensitive files also SHA256; symlinks not followed"}


def write_json(path, data):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_inventory(path, records):
    with path.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
        handle.flush(); os.fsync(handle.fileno())


def rename_no_replace(source, target):
    """Linux renameat2(RENAME_NOREPLACE), refusing unsafe overwrite fallbacks."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RuntimeError("renameat2 unavailable; refusing a potentially overwriting rename")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        if code in {errno.ENOSYS, errno.EINVAL}:
            raise RuntimeError("Filesystem does not support no-replace rename; no unsafe fallback used")
        raise OSError(code, os.strerror(code), str(source), str(target))


def validate_snapshots(root, archive):
    snapshots = prerequisites(archive)
    if not all(item["present_nonempty"] for item in snapshots.values()):
        raise RuntimeError("--apply requires root-completed state/core_snapshot.tar.gz and state/history.bundle")
    if any(not Path(item["path"]).resolve().is_relative_to(archive) for item in snapshots.values()):
        raise RuntimeError("Snapshot paths must remain inside this archive")
    snapshot = archive / "state/core_snapshot.tar.gz"
    with tarfile.open(snapshot, "r:gz") as bundle:
        count = sum(1 for _ in bundle)
    if not count:
        raise RuntimeError("Core snapshot contains no entries")
    checked = subprocess.run(["git", "bundle", "verify", str(archive / "state/history.bundle")], cwd=root, capture_output=True, text=True, check=False)
    if checked.returncode:
        raise RuntimeError("history.bundle failed git bundle verify; no source moves performed")
    for item in snapshots.values():
        item["sha256"] = sha256(Path(item["path"]))
    return snapshots


def apply(root, archive):
    archive.mkdir(parents=True, exist_ok=True)
    if archive.is_symlink() or archive.resolve() != archive:
        raise RuntimeError("Archive must be a real directory at its fixed path")
    with (archive / ".archive_apply.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current_plan = plan(root, archive)
        if current_plan["conflicts"]:
            raise RuntimeError("Refusing all moves: both source and target exist for " + ", ".join(current_plan["conflicts"]))
        for relative in ("legacy", "private", "state", "state/move_inventories"):
            parent = archive / relative
            if exists(parent) and (parent.is_symlink() or not parent.is_dir()):
                raise RuntimeError("Archive parent must be a real directory: " + relative)
        snapshots = validate_snapshots(root, archive)
        # Check every planned source before the first mutation.
        for item in current_plan["items"]:
            if item["status"] != "planned":
                continue
            source = root / item["source"]
            if item["source"] == ".env.local.bk" and (source.is_symlink() or not source.is_file()):
                raise RuntimeError("Credential backup must be a regular file for private mode0600 archival")
            if item.get("special_files"):
                raise RuntimeError("Special files require manual review: " + item["source"])
            if source.lstat().st_dev != archive.stat().st_dev:
                raise RuntimeError("Cross-filesystem move refused: " + item["source"])
        manifest_path = archive / "move_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("archive_id") != ARCHIVE_ID or manifest.get("root") != str(root):
                raise RuntimeError("Existing manifest belongs to another archive/root")
        else:
            manifest = {"archive_id": ARCHIVE_ID, "root": str(root), "created_at": utcnow(), "items": {}, "status": "not_started"}
        manifest["prerequisites"] = snapshots
        manifest["status"] = "in_progress"
        manifest["last_started_at"] = utcnow()
        invdir = archive / "state/move_inventories"; invdir.mkdir(parents=True, exist_ok=True)
        write_json(archive / "move_plan_at_apply.json", current_plan)
        write_json(manifest_path, manifest)

        def checkpoint():
            write_json(manifest_path, manifest)
            write_json(archive / "pathmap.json", {"archive_id": ARCHIVE_ID, "root": str(root),
                "restore_policy": "After stopping writers, move archive destination back to source only if the original source is absent. Never overwrite. Consult item inventories for verification.",
                "paths": [{"original_relative_path": name, "archived_relative_path": destination(name), "status": manifest["items"].get(name, {}).get("status", "not_processed")} for name in ALLOWLIST]})

        for item in current_plan["items"]:
            name = item["source"]; source = root / name; target = archive / destination(name)
            prior = manifest["items"].get(name, {})
            if item["status"] == "absent":
                manifest["items"][name] = {**item, "status": "absent", "checked_at": utcnow()}; checkpoint(); continue
            if item["status"] == "already_moved":
                after, _ = inventory(target)
                expected = prior.get("before", {}).get("inventory_sha256")
                verified = bool(expected and expected == after["inventory_sha256"])
                if expected and not verified:
                    raise RuntimeError("Already-moved target no longer matches recorded inventory: " + name)
                manifest["items"][name] = {**prior, **item, "after": after, "status": "already_moved", "verified": verified,
                    "verification_note": None if verified else "No original inventory exists; destination presence alone is not proof of historical equivalence."}
                checkpoint(); continue
            if exists(target):
                raise RuntimeError("Target appeared during execution; refusing overwrite: " + str(target))
            before, records = inventory(source)
            if before["inventory_sha256"] != item["inventory_sha256"]:
                raise RuntimeError("Source changed since apply preflight; no move for " + name)
            inventory_name = name.replace(".", "_") + "." + before["inventory_sha256"] + ".before.jsonl"
            before_path = invdir / inventory_name
            if not before_path.exists():
                write_inventory(before_path, records)
            manifest["items"][name] = {**item, "before": before, "before_inventory": str(before_path.relative_to(archive)), "status": "moving", "started_at": utcnow()}
            checkpoint()
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == ".env.local.bk":
                target.parent.chmod(0o700)
            try:
                rename_no_replace(source, target)
                if name == ".env.local.bk" and not target.is_symlink():
                    target.chmod(0o600)
                after, after_records = inventory(target)
                after_path = invdir / (name.replace(".", "_") + "." + after["inventory_sha256"] + ".after.jsonl")
                if not after_path.exists():
                    write_inventory(after_path, after_records)
                same = before["inventory_sha256"] == after["inventory_sha256"]
                entry = manifest["items"][name]
                entry.update({"after": after, "after_inventory": str(after_path.relative_to(archive)),
                    "status": "moved_verified" if same else "verification_failed", "verified": same, "completed_at": utcnow()})
                checkpoint()
                if not same:
                    raise RuntimeError("Moved inventory mismatch; preserved destination requires manual review: " + name)
            except BaseException as exc:
                manifest["status"] = "interrupted_or_failed"
                manifest["items"][name]["error_type"] = type(exc).__name__
                checkpoint(); raise
        manifest["status"] = "completed"
        manifest["completed_at"] = utcnow()
        checkpoint()
        return {"archive_id": ARCHIVE_ID, "status": manifest["status"], "manifest": str(manifest_path), "pathmap": str(archive / "pathmap.json"),
                "items": [{"source": name, "destination": destination(name), "status": entry["status"], "verified": entry.get("verified")} for name, entry in manifest["items"].items()]}


def main():
    parser = argparse.ArgumentParser(__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Read-only allowlist inventory; default")
    mode.add_argument("--apply", action="store_true", help="Move after snapshot verification; refuses existing targets")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    archive = root / "archive" / ARCHIVE_ID
    if not root.is_dir():
        parser.error("Project root is not a directory")
    try:
        result = apply(root, archive) if args.apply else plan(root, archive)
    except (OSError, RuntimeError, ValueError, tarfile.TarError) as exc:
        print(json.dumps({"status": "refused_or_interrupted", "error_type": type(exc).__name__, "reason": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
