"""Shared build locking, checked cleanup and isolated Vivado sessions.

Uses only the Python standard library. The guard owns an OS lock for the whole
pipeline, including collection. Nested stages inherit its token. The lock file
is removed on the way out, which is why acquisition checks that the file it
locked is still the file at the path: an unlink alone would let a holder of the
orphaned inode run beside whoever creates the next one. POSIX unlinks under the
lock, Windows cannot delete an open file and so closes first, leaving the file
alone if another run already holds it.

Every path, generated name and environment variable it uses is owned by
build_config.py. The three roots below are mirrored out of it because they are
what a check moves to run this layer against a disposable workspace.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

import build_config as config

SRC = config.SRC_DIR
ROOT = config.REPO_DIR
LOCK = ROOT / config.LOCK_NAME


def active_tools():
    """Reject live vendor tools; never kill an unrelated process automatically."""
    named = "|".join((*config.TOOLS, config.TCLSH + ".*"))
    if os.name == "nt":
        query = (
            "$ErrorActionPreference='Stop'; Get-Process | "
            "Where-Object {$_.ProcessName -match '^(" + named + ")$'} | "
            "Select-Object Id,ProcessName,Path | ConvertTo-Json -Compress"
        )
        data = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query], text=True
        ).strip()
        records = json.loads(data) if data else []
        if isinstance(records, dict):
            records = [records]
        return [f"PID {r['Id']}: {r['ProcessName']} ({r.get('Path') or 'path unavailable'})"
                for r in records if r["ProcessName"].lower() in config.TOOLS or
                re.search(config.TOOL_PATH_PATTERN, r.get("Path") or "", re.I)]
    data = subprocess.check_output(["ps", "-eo", "pid=,comm=,args="], text=True)
    found = []
    for line in data.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) < 3:
            continue
        _, name, args = fields
        if Path(name).name in config.TOOLS or (
            name.startswith(config.TCLSH) and re.search(config.TOOL_PATH_PATTERN, args, re.I)
        ):
            found.append(line.strip())
    return found


def preflight():
    found = active_tools()
    if found:
        raise RuntimeError("Active FPGA tools detected. Close them before rebuilding:\n  "
                           + "\n  ".join(found))


def lock_file(handle):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release(handle):
    if os.name != "nt":
        LOCK.unlink(missing_ok=True)
    handle.close()
    if os.name == "nt":
        try:
            LOCK.unlink()
        except OSError:
            pass


@contextmanager
def guard():
    # Metadata starts after the Windows byte-range lock, so descendants can read it.
    if os.environ.get(config.GUARD_TOKEN) and LOCK.exists():
        with LOCK.open("rb") as handle:
            handle.seek(1)
            metadata = handle.read().decode("utf-8")
        if metadata == os.environ[config.GUARD_TOKEN]:
            yield
            return
    handle = LOCK.open("a+b")
    try:
        if LOCK.stat().st_size == 0:
            handle.write(b" ")
            handle.flush()
        lock_file(handle)
        if os.stat(LOCK).st_ino != os.fstat(handle.fileno()).st_ino:
            raise OSError("the lock file was replaced during acquisition")
    except OSError as exc:
        handle.close()
        raise RuntimeError("Another build/clean owns this workspace. Wait for it to finish.") from exc
    try:
        preflight()
        token = f"{os.getpid()}:{uuid.uuid4()}"
        handle.seek(1)
        handle.truncate()
        handle.write(token.encode())
        handle.flush()
        previous = os.environ.get(config.GUARD_TOKEN)
        os.environ[config.GUARD_TOKEN] = token
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(config.GUARD_TOKEN, None)
            else:
                os.environ[config.GUARD_TOKEN] = previous
    finally:
        release(handle)


def checked_remove(path: Path, base: Path):
    """Remove an explicitly selected generated target, rejecting links out of scope."""
    resolved, root = path.resolve(), base.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise RuntimeError(f"Refusing deletion outside generated-file scope: {path}")
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        # A junction inside a generated project must never take deletion elsewhere.
        for entry in path.rglob("*"):
            if not entry.resolve().is_relative_to(root):
                raise RuntimeError(f"Refusing cleanup through an external link: {entry}")
        shutil.rmtree(path)
    else:
        path.unlink()
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"Cleanup did not remove {path}")


def caches():
    """Every bytecode cache under the configured roots, with the scope it sits in.

    Not just the packages that happen to have one today: a cache belonging to
    a module that has since moved is what makes a resume import something that
    no longer exists. Excluded directories are skipped whole rather than
    walked, so a clean never pays for descending into the virtual environment.
    """
    for name in config.PYCACHE_ROOTS:
        root = ROOT / name
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name in config.PYCACHE_EXCLUDE or not child.is_dir():
                continue
            if child.name == config.PYCACHE_NAME:
                yield child, root
                continue
            for cache in sorted(child.rglob(config.PYCACHE_NAME)):
                yield cache, root


def clean(stages, dry_run=False):
    for marker in config.WORKSPACE_MARKERS:
        if not (SRC / marker).is_file():
            raise RuntimeError(f"Refusing cleanup: missing workspace marker {marker}")
    targets = []
    for stage in stages:
        for pattern in config.CLEAN_PATTERNS[stage]:
            targets.extend((path, SRC) for path in sorted(SRC.glob(pattern)))
    targets.extend(caches())
    print(f"Cleaning {ROOT} ({'dry run' if dry_run else 'checked deletion'}): {' '.join(stages)}", flush=True)
    seen = set()
    for path, base in targets:
        if path in seen:
            continue
        seen.add(path)
        if not dry_run:
            checked_remove(path, base)
        print(f"  {'would remove' if dry_run else 'removed'} {path.relative_to(ROOT)}", flush=True)


def command(executable, args):
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        # cmd's /s /c requires outer quotes around the complete quoted command.
        parts = [str(executable), *map(str, args)]
        if any(re.search(r'["\r\n%]', arg) for arg in parts):
            raise RuntimeError("Batch command paths/arguments cannot contain quotes, newlines or %")
        quoted = " ".join('"' + arg + '"' for arg in parts)
        prefix = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"])
        return prefix + ' "' + quoted + '"'
    if str(executable).endswith(".sh"):
        return [os.environ.get(config.BASH_OVERRIDE, "bash"), str(executable), *map(str, args)]
    return [str(executable), *map(str, args)]


def fingerprint(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def vivado(tool, args):
    if len(args) > 3:
        raise RuntimeError("Usage: vivado [width [build [bd]]]")
    hls = SRC / config.HLS_SUBDIR
    width = args[0] if args else ""
    if not width:
        match = re.search(rf"^\s*#define\s+{config.SELECTED_WIDTH_DEFINE}\s+(\d+)\s*$",
                          (hls / config.SELECTED_WIDTH_NAME).read_text(), re.M)
        if not match:
            raise RuntimeError("Cannot read selected width; run export first")
        width = match[1]
    build = (args[1] if len(args) > 1 else config.DEFAULT_BUILD).upper()
    mode = args[2] if len(args) > 2 else config.DEFAULT_VIVADO_MODE
    if (not width.isdecimal() or int(width) < 1 or build not in config.BUILDS
            or mode not in config.VIVADO_MODES):
        raise RuntimeError("Expected positive width, build %s, and mode %s"
                           % ("/".join(config.BUILDS), " or ".join(config.VIVADO_MODES)))
    preflight()  # Also catch orphaned tools left by a previous variant in all.*.
    folder = SRC / config.VIVADO_SUBDIR
    ip = hls / config.HLS_PROJECT.format(width=width, build=build) / config.HLS_SOLUTION / config.HLS_IP
    if not (ip / config.HLS_IP_MARKER).is_file():
        raise RuntimeError(f"No packaged HLS IP: {ip}")
    log_root = Path(os.environ.get(config.VIVADO_LOG_DIR, folder / config.LOG_SUBDIR)).resolve()
    log_root.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix=f"w{width}_{build}-", dir=log_root))
    print(f"Vivado diagnostics: {session}", flush=True)
    inputs = list(ip.rglob("*")) + list((folder / config.TCL_SUBDIR).glob("*.tcl"))
    manifest = {
        "started_utc": datetime.now(timezone.utc).isoformat(), "tool": str(Path(tool).resolve()),
        "width": width, "build": build, "mode": mode, "phases": {},
        "input_sha256": fingerprint(inputs),
    }
    manifest_file = session / config.MANIFEST_NAME
    project = folder / config.VIVADO_PROJECT.format(width=width, build=build)
    stem = config.BITSTREAM_STEM.format(width=width, build=build)
    try:
        # Only this build's generated outputs; keep the other variants intact.
        checked_remove(project, folder)
        for suffix in config.BITSTREAM_SUFFIXES:
            checked_remove(folder / config.BIT_SUBDIR / f"{stem}.{suffix}", folder)
        for report in folder.glob(config.REPORT_GLOB.format(stem=stem)):
            checked_remove(report, folder)
        phases = [("board", config.BOARD_SCRIPT, []),
                  ("bd", config.DESIGN_SCRIPT, [width, build, config.VIVADO_MODE_BD])]
        if mode == config.VIVADO_MODE_FULL:
            phases.append(("impl", config.DESIGN_SCRIPT,
                           [width, build, config.DESIGN_IMPL_ARG]))
        for name, script, parameters in phases:
            preflight()
            phase_dir = session / name
            phase_dir.mkdir()
            marker = phase_dir / "success.txt"
            env = dict(os.environ, **{config.VIVADO_STATUS_FILE: str(marker)})
            invocation = ["-mode", "batch", "-log", str(phase_dir / "vivado.log"),
                          "-journal", str(phase_dir / "vivado.jou"), "-source", str(folder / config.TCL_SUBDIR / script)]
            if parameters:
                invocation += ["-tclargs", *parameters]
            print(f"Vivado phase: {name} (fresh process)", flush=True)
            rc = subprocess.call(command(tool, invocation), cwd=phase_dir, env=env)
            completed = marker.is_file() and marker.read_text().strip() == "0"
            manifest["phases"][name] = {"exit_code": rc, "completed": completed}
            if rc or not completed:
                raise RuntimeError(f"Vivado {name} failed (exit {rc}); inspect {phase_dir}")
        if mode == config.VIVADO_MODE_FULL:
            for suffix in config.BITSTREAM_SUFFIXES:
                output = folder / config.BIT_SUBDIR / f"{stem}.{suffix}"
                if not output.is_file() or output.stat().st_size == 0:
                    raise RuntimeError(f"Vivado did not produce {output}")
        manifest["result"] = "OK"
    except BaseException as exc:
        manifest["result"] = f"FAILED: {exc}"
        raise
    finally:
        # Preserve generated run logs as well as the driver session on failures.
        runs = project / f"{project.name}.runs"
        if runs.is_dir():
            for source in runs.rglob("*"):
                if source.is_file() and (source.suffix in config.RUN_LOG_SUFFIXES
                                         or source.name.endswith(config.RUN_LOG_EXTRA)):
                    target = session / "runs" / source.relative_to(runs)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build_menu():
    """The picker's list: one line per build, with the default marked."""
    for letter in config.BUILDS:
        mark = "  (default)" if letter == config.DEFAULT_BUILD else ""
        print(f"  {letter}  {config.BUILD_LABELS[letter]}{mark}")


def resolve_build(answer):
    """One typed answer as a canonical letter. Empty means the default."""
    letter = (answer or "").strip().upper() or config.DEFAULT_BUILD
    if letter not in config.BUILDS:
        raise RuntimeError("no such build: %s. Pick one of %s."
                           % (answer.strip(), ", ".join(config.BUILDS)))
    return letter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("preflight")
    run = sub.add_parser("guard")
    run.add_argument("script")
    run.add_argument("args", nargs=argparse.REMAINDER)
    cleanup = sub.add_parser("clean")
    cleanup.add_argument("--dry-run", "-n", action="store_true")
    cleanup.add_argument("stages", nargs="*")
    impl = sub.add_parser("vivado")
    impl.add_argument("--tool", required=True)
    impl.add_argument("args", nargs="*")
    sub.add_parser("list-builds")
    pick = sub.add_parser("resolve-build")
    pick.add_argument("answer", nargs="?", default="")
    ns = parser.parse_args()
    if ns.action == "clean" and any(s not in config.CLEAN_PATTERNS for s in ns.stages):
        parser.error("clean stages must be train, export, hls or vivado")
    try:
        # Neither of these touches the tree, so neither waits on the lock. A
        # menu that blocked because a build was running would be absurd.
        if ns.action == "list-builds":
            build_menu()
            return 0
        if ns.action == "resolve-build":
            print(resolve_build(ns.answer))
            return 0
        with guard():
            if ns.action == "preflight":
                preflight()
            elif ns.action == "guard":
                return subprocess.call(command(ns.script, ns.args))
            elif ns.action == "clean":
                clean(ns.stages or list(config.CLEAN_PATTERNS), ns.dry_run)
            else:
                vivado(ns.tool, ns.args)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Build interrupted. Check for remaining FPGA processes before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
