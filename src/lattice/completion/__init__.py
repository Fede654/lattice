"""Shell completion callbacks for the Lattice CLI.

Click invokes these in a throwaway process on every <Tab>, outside any command,
so they must be fast and must never raise: an exception surfaces as shell
noise, not as a Python traceback. Every callback therefore degrades to "no
suggestions" rather than failing, and reads the board directly instead of going
through the command machinery.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
from click.shell_completion import CompletionItem

from lattice.core.relationships import RELATIONSHIP_TYPES
from lattice.storage.fs import LATTICE_DIR, find_root


def _lattice_dir() -> Path | None:
    """Return the active ``.lattice/`` directory, or ``None``.

    Uses the same resolution as every command — ``LATTICE_ROOT`` first, then a
    walk up that is transparent through git worktrees — so completion offers
    exactly the tasks the command would act on.
    """
    try:
        root = find_root()
    except Exception:
        return None
    return None if root is None else root / LATTICE_DIR


def _items(values, incomplete: str, *, sort: bool = True) -> list[CompletionItem]:
    """CompletionItems for the values matching *incomplete*.

    Sorted by default, which is what identifiers and names want. Pass
    ``sort=False`` where the given order carries meaning — workflow statuses
    read as a sequence (backlog, planned, in_progress, review, done), and
    alphabetising them would bury the one you usually want next.
    """
    ordered = sorted(values) if sort else list(values)
    return [CompletionItem(v) for v in ordered if v.startswith(incomplete)]


def _names_in(directory: Path | None, incomplete: str) -> list[CompletionItem]:
    """Complete from the stems of ``*.json`` files in *directory*."""
    if directory is None or not directory.is_dir():
        return []
    try:
        return _items((p.stem for p in directory.glob("*.json")), incomplete)
    except OSError:
        return []


def complete_task_id(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete task short IDs (e.g. ``LAT-1``) from the id index."""
    lattice_dir = _lattice_dir()
    if lattice_dir is None:
        return []
    try:
        from lattice.storage.short_ids import load_id_index

        index = load_id_index(lattice_dir)
    except Exception:
        return []
    return _items((index.get("map") or {}).keys(), incomplete)


def complete_status(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete statuses from the project's workflow.

    Falls back to the built-in defaults when there is no project to read, so
    completion still works before ``lattice init``. That fallback is derived
    from the same config module the CLI uses rather than a second hardcoded
    list, which would silently drift as workflow presets change.
    """
    lattice_dir = _lattice_dir()
    if lattice_dir is not None:
        try:
            data = json.loads((lattice_dir / "config.json").read_text())
            configured = (data.get("workflow") or {}).get("statuses")
            if isinstance(configured, list) and all(isinstance(s, str) for s in configured):
                return _items(configured, incomplete, sort=False)
        except Exception:
            pass
    try:
        from lattice.core.config import default_config

        return _items(default_config()["workflow"]["statuses"], incomplete, sort=False)
    except Exception:
        return []


def complete_actor(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete actor IDs seen as assignees on the board."""
    lattice_dir = _lattice_dir()
    if lattice_dir is None:
        return []
    tasks_dir = lattice_dir / "tasks"
    if not tasks_dir.is_dir():
        return []
    actors: set[str] = set()
    try:
        with os.scandir(tasks_dir) as entries:
            for entry in entries:
                if not entry.is_file() or not entry.name.endswith(".json"):
                    continue
                try:
                    actor = json.loads(Path(entry.path).read_text()).get("assigned_to")
                except Exception:
                    continue
                if isinstance(actor, str) and actor:
                    actors.add(actor)
    except OSError:
        return []
    return _items(actors, incomplete)


def complete_resource_name(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete resource names."""
    lattice_dir = _lattice_dir()
    return _names_in(None if lattice_dir is None else lattice_dir / "resources", incomplete)


def complete_session_name(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete session names."""
    lattice_dir = _lattice_dir()
    return _names_in(None if lattice_dir is None else lattice_dir / "sessions", incomplete)


def complete_project_name(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete project names discovered under the configured scan paths.

    Used by the multi-project commands, where a value names a whole board
    rather than something inside one. Honours $LATTICE_SCAN_PATH and the
    ignore rules, so it offers exactly the projects the command would scan.
    """
    try:
        from lattice.storage.discovery import (
            discover_projects,
            resolve_ignore_patterns,
            resolve_scan_paths,
        )

        projects = discover_projects(
            resolve_scan_paths(None), ignore=resolve_ignore_patterns(None)
        )
    except Exception:
        return []
    return _items((p.name for p in projects), incomplete)


def complete_relationship_type(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete relationship types for link/unlink."""
    return _items(RELATIONSHIP_TYPES, incomplete)
