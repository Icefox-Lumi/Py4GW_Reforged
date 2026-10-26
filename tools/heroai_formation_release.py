"""Allowlisted Option A deployment/rollback. Run only after independent review.

The release bundle contains this tool, release.json and artifact/<relative path>.
Production targets are fixed. Fixture targets must be beneath bundle/fixtures.
No Git operations or account configuration access occur here.
Deployment and rollback require exclusive maintenance: all clients stopped and
no other writer modifying the target files, package, or receipts. Hash checks do
not provide an atomic compare-and-replace against arbitrary concurrent writers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

TESTS_ROOT = Path(r"C:\Users\O_o\Desktop\Py4GW_Reforged-main TESTS")
RECOVERY_ROOT = Path(r"C:\Users\O_o\Desktop\Py4GW-Recovery")
FILES = (
    "Widgets/Automation/Multiboxing/HeroAI Actions.py",
    "Py4GWCoreLib/HeroAI/commands.py",
    "Py4GWCoreLib/HeroAI/command_api.py",
    "Py4GWCoreLib/GlobalCache/SharedMemory.py",
    "Py4GWCoreLib/GlobalCache/shared_memory_src/PartyFormation.py",
    "Py4GWCoreLib/GlobalCache/shared_memory_src/PartyFormationRuntime.py",
    "Widgets/System/Messaging.py",
    "Py4GWCoreLib/GlobalCache/PartyCache.py",
)


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def safe_path(root: Path, relative: str) -> Path:
    if relative not in FILES:
        raise ValueError(f"Path outside release allowlist: {relative}")
    root = root.absolute()
    target = root.joinpath(*relative.split("/"))
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes target root")
    for ancestor in (target, *target.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError(f"Link/junction not permitted: {ancestor}")
        if ancestor == root:
            break
    if target.exists() and not target.is_file():
        raise ValueError(f"Target is not a regular file: {target}")
    return target


def check_target(bundle: Path, target: Path, fixture: bool) -> None:
    if fixture:
        if (
            not target.resolve().is_relative_to((bundle / "fixtures").resolve())
            or not (target / ".formation-fixture").is_file()
        ):
            raise ValueError("Fixture must have a marker beneath this bundle's fixtures directory")
        if target.resolve() == TESTS_ROOT.resolve():
            raise ValueError("TESTS cannot be a fixture")
    elif target.resolve() != TESTS_ROOT.resolve():
        raise ValueError("Production target must be the exact TESTS root")
    elif not bundle.resolve().is_relative_to(RECOVERY_ROOT.resolve()):
        raise ValueError("Production recovery bundle must be in the permanent Py4GW-Recovery directory")
    for relative in FILES:
        safe_path(target, relative)


def require_stopped_clients() -> None:
    """Read-only detection. Renamed clients with inaccessible modules remain a documented limit."""
    command = r"""
$ErrorActionPreference = 'Stop'
$hits = @()
foreach ($process in Get-Process) {
    $found = $process.ProcessName -match '^(Gw|Gw1|GuildWars|Guild Wars|Py4GW.*)$'
    if (-not $found) {
        try { $found = @($process.Modules | Where-Object { $_.ModuleName -match '^Py4GW.*\.dll$' }).Count -gt 0 } catch { }
    }
    if ($found) { $hits += $process.ProcessName + ':' + $process.Id }
}
ConvertTo-Json -InputObject @($hits) -Compress
"""
    result = subprocess.run(
        [
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    hits = json.loads(result.stdout)
    if hits:
        raise RuntimeError("Stop all Guild Wars/injected clients before continuing: " + ", ".join(hits))


def write_json(path: Path, value: object) -> None:
    data = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".pending")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def install_bytes(path: Path, data: bytes, installation: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".formation-" + installation + ".tmp")
    if temporary.exists():
        raise RuntimeError(f"Unexpected install temporary file: {temporary}")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if digest(temporary) != hashlib.sha256(data).hexdigest():
            raise RuntimeError("Temporary write verification failed")
        os.replace(temporary, path)
    finally:
        if temporary.is_file():
            temporary.unlink()


def read_release(bundle: Path, approved_hash: str) -> dict[str, Any]:
    if digest(bundle / "release.json") != approved_hash.lower():
        raise RuntimeError("Release manifest does not match the explicitly approved SHA-256")
    manifest = json.loads((bundle / "release.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or set(manifest.get("files", {})) != set(FILES):
        raise ValueError("Release allowlist/schema mismatch")
    for relative in FILES:
        artifact = safe_path(bundle / "artifact", relative)
        if digest(artifact) != manifest["files"][relative]["deployed_sha256"]:
            raise RuntimeError(f"Artifact hash mismatch: {relative}")
    return manifest


def restore(receipt: Path, *, fixture: bool = False) -> str:
    record = json.loads((receipt / "installation.json").read_text(encoding="utf-8"))
    bundle = Path(record["bundle"])
    target = Path(record["target"])
    if receipt.resolve().parent != (bundle / "installations").resolve():
        raise ValueError("Receipt must belong to the bundle's installations directory")
    if record.get("schema") != 1 or set(record.get("files", {})) != set(FILES):
        raise ValueError("Installation allowlist/schema mismatch")
    check_target(bundle, target, fixture)
    if not fixture:
        require_stopped_clients()
    # Preflight the ENTIRE restore set, including originals, before the first write.
    todo: list[str] = []
    touched = set(record["completed"])
    if record.get("pending") is not None:
        touched.add(record["pending"])
    for relative in FILES:
        entry = record["files"][relative]
        current = digest(safe_path(target, relative))
        original = entry["original_sha256"]
        if original is not None and digest(safe_path(receipt / "original", relative)) != original:
            raise RuntimeError(f"Original backup damaged: {relative}")
        if current == original:
            continue
        if relative not in touched:
            raise RuntimeError(f"Untouched file changed after preflight; nothing restored: {relative}")
        if current != entry["deployed_sha256"]:
            raise RuntimeError(f"Later edit or unexpected state; nothing restored: {relative}")
        todo.append(relative)
    if not todo:
        return "already restored"
    try:
        for relative in todo:
            entry = record["files"][relative]
            destination = safe_path(target, relative)
            if digest(destination) != entry["deployed_sha256"]:
                raise RuntimeError(f"Destination changed during rollback; stopped: {relative}")
            record["rollback_pending"] = relative
            write_json(receipt / "installation.json", record)
            if entry["original_sha256"] is None:
                destination.unlink()  # Only an exact, patch-added file from this receipt.
            else:
                data = safe_path(receipt / "original", relative).read_bytes()
                if hashlib.sha256(data).hexdigest() != entry["original_sha256"]:
                    raise RuntimeError(f"Backup integrity mismatch during rollback: {relative}")
                install_bytes(destination, data, record["id"])
            if digest(destination) != entry["original_sha256"]:
                raise RuntimeError(f"Restored file integrity mismatch: {relative}")
            record["restored"].append(relative)
            record["rollback_pending"] = None
            write_json(receipt / "installation.json", record)
        for relative in FILES:
            if digest(safe_path(target, relative)) != record["files"][relative]["original_sha256"]:
                raise RuntimeError(f"Final rollback verification failed: {relative}")
        record["state"] = "restored"
        record["pending"] = None
        write_json(receipt / "installation.json", record)
    except Exception as exc:
        record["state"] = "rollback_failed"
        record["rollback_error"] = str(exc)
        write_json(receipt / "installation.json", record)
        raise RuntimeError(f"Rollback incomplete: {exc}. Preserve receipt: {receipt}") from exc
    return "restored"


def deploy(
    bundle: Path, target: Path, approved_hash: str, *, fixture: bool = False, fail_after: int | None = None
) -> Path:
    if fail_after is not None and not fixture:
        raise ValueError("Failure injection is fixture-only")
    check_target(bundle, target, fixture)
    manifest = read_release(bundle, approved_hash)
    if not fixture and manifest.get("approvals", {}).get("deployment") is not True:
        raise RuntimeError("Deployment approval is false; no production installation is permitted")
    if not fixture and manifest.get("release_gates") != {
        "independent_review": True,
        "deployed_native_contract": True,
    }:
        raise RuntimeError(
            "Release is gated: independent review and deployed native invitation contract are unapproved"
        )
    if not fixture:
        require_stopped_clients()
    for relative in FILES:
        if digest(safe_path(target, relative)) != manifest["files"][relative]["expected_sha256"]:
            raise RuntimeError(f"Baseline drift; nothing installed: {relative}")
    installation = uuid.uuid4().hex
    receipt = bundle / "installations" / installation
    receipt.mkdir(parents=True, exist_ok=False)
    record: dict[str, Any] = {
        "schema": 1,
        "id": installation,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "target": str(target.resolve()),
        "bundle": str(bundle.resolve()),
        "approved_manifest_sha256": approved_hash.lower(),
        "state": "prepared",
        "files": {},
        "completed": [],
        "restored": [],
        "pending": None,
    }
    for relative in FILES:
        entry = manifest["files"][relative]
        original = safe_path(target, relative)
        original_hash = digest(original)
        if original_hash != entry["expected_sha256"]:
            raise RuntimeError(f"Concurrent baseline change before install: {relative}")
        if original_hash is not None:
            backup = safe_path(receipt / "original", relative)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(original.read_bytes())
            if digest(backup) != original_hash:
                raise RuntimeError(f"Backup verification failed: {relative}")
        record["files"][relative] = {"original_sha256": original_hash, "deployed_sha256": entry["deployed_sha256"]}
    write_json(receipt / "installation.json", record)
    write_json(bundle / "latest-installation.json", {"receipt": str(receipt)})
    try:
        for index, relative in enumerate(FILES):
            if fail_after == index:
                raise OSError("Injected fixture installation failure")
            entry = record["files"][relative]
            destination = safe_path(target, relative)
            if digest(destination) != entry["original_sha256"]:
                raise RuntimeError(f"Concurrent edit during installation: {relative}")
            artifact = safe_path(bundle / "artifact", relative)
            data = artifact.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["deployed_sha256"]:
                raise RuntimeError(f"Artifact changed during installation: {relative}")
            record["pending"] = relative
            write_json(receipt / "installation.json", record)
            install_bytes(destination, data, installation)
            record["completed"].append(relative)
            record["pending"] = None
            write_json(receipt / "installation.json", record)
        record["state"] = "installed"
        write_json(receipt / "installation.json", record)
    except Exception as exc:
        record["state"] = "installation_failed"
        record["error"] = str(exc)
        write_json(receipt / "installation.json", record)
        try:
            restore(receipt, fixture=fixture)
        except Exception as recovery_error:
            raise RuntimeError(f"Partial installation; recovery refused: {recovery_error}. Receipt: {receipt}") from exc
        raise RuntimeError(f"Installation failed and original files restored. Receipt: {receipt}") from exc
    write_json(bundle / "latest-installation.json", {"receipt": str(receipt)})
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("deploy", "rollback"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--approved-manifest-sha256")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--confirm-clients-stopped", action="store_true")
    parser.add_argument("--confirm-exclusive-maintenance", action="store_true")
    args = parser.parse_args()
    if not args.confirm_clients_stopped:
        parser.error(
            "Confirm ALL Guild Wars/injected clients are stopped; process detection cannot identify every renamed client."
        )
    if not args.confirm_exclusive_maintenance:
        parser.error(
            "Exclusive maintenance required: no other process may modify target files or this recovery package."
        )
    if args.mode == "deploy":
        if not args.approved_manifest_sha256:
            parser.error("An independently approved manifest SHA-256 is required")
        print(deploy(args.bundle, TESTS_ROOT, args.approved_manifest_sha256))
    else:
        receipt = args.receipt
        if receipt is None:
            receipt = Path(json.loads((args.bundle / "latest-installation.json").read_text())["receipt"])
        print(restore(receipt))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FAILED: {error}", file=sys.stderr)
        sys.exit(1)
