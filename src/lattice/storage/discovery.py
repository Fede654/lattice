"""Discovery of Lattice projects across a filesystem tree.

Lattice is single-project by design: one ``.lattice/`` directory describes one
project, and task state lives beside the code it describes. That property is
worth keeping — cloning a repo brings its board with it.

The cost is that someone working across many repositories has no single place
to see all of them. This module supplies the missing half: a read-only scan
that locates every ``.lattice/`` root under one or more search paths, so the
dashboard can offer them as a choice without merging the projects themselves.

Nothing here mutates state. Discovery is always safe to run.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from lattice.storage.fs import LATTICE_DIR

#: Environment variable naming the directories to scan for Lattice projects.
#: Accepts an ``os.pathsep``-separated list (``:`` on POSIX), so several
#: unrelated trees can be watched at once. ``~`` is expanded.
LATTICE_SCAN_PATH_ENV = "LATTICE_SCAN_PATH"

#: How deep below each search path to look. Repositories are conventionally one
#: level under a workspace directory (``~/REPOS/<project>/.lattice``), so 3 is
#: generous while still bounding the walk on large trees.
DEFAULT_MAX_DEPTH = 3

#: Upper bound on path segments used when disambiguating duplicate names.
_MAX_NAME_SEGMENTS = 4

#: Directories that never contain a project root worth reporting, and which are
#: expensive to descend into.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        ".worktrees",
        ".tox",
        ".next",
        ".cache",
    }
)


@dataclass(frozen=True)
class DiscoveredProject:
    """A Lattice project found on disk.

    Attributes
    ----------
    root:
        Directory containing ``.lattice/`` (the project root, not ``.lattice``).
    lattice_dir:
        The ``.lattice/`` directory itself.
    name:
        Display name, unique within one scan. Normally the root's directory
        name; when several roots share it (a checkout and a copy of the same
        project, say), enough parent segments are prepended to tell them apart.
        Uniqueness matters because this name is the filter key in the aggregate
        view — two projects sharing one name would be indistinguishable.
    project_code:
        ``project_code`` from ``config.json``, or ``None`` if unreadable. This
        is the short-ID prefix (e.g. ``HRM``) and is what "filter by prefix"
        means in the aggregate view.
    project_name:
        Human-readable ``project_name`` from config, when set.
    error:
        Populated when the project was located but its config could not be
        read. The project is still reported — a broken project is exactly the
        kind of thing an overview should surface rather than hide.
    """

    root: Path
    lattice_dir: Path
    name: str
    project_code: str | None = None
    project_name: str | None = None
    error: str | None = None


def scan_paths_from_env(env: dict[str, str] | None = None) -> list[Path]:
    """Return the configured scan paths, or an empty list when unset.

    Reads :data:`LATTICE_SCAN_PATH_ENV`, splitting on ``os.pathsep``. Blank
    segments are ignored so a trailing separator is harmless. ``~`` is
    expanded; paths are not required to exist (a missing path is simply
    skipped during the scan).
    """
    source = os.environ if env is None else env
    raw = source.get(LATTICE_SCAN_PATH_ENV)
    if not raw:
        return []
    out: list[Path] = []
    for segment in raw.split(os.pathsep):
        segment = segment.strip()
        if segment:
            out.append(Path(segment).expanduser())
    return out


def resolve_scan_paths(
    explicit: list[str] | tuple[str, ...] | None = None,
    *,
    env: dict[str, str] | None = None,
    fallback: Path | None = None,
) -> list[Path]:
    """Resolve which directories to scan.

    Precedence: *explicit* paths (CLI flags) > :data:`LATTICE_SCAN_PATH_ENV` >
    *fallback* (defaults to the current working directory). Duplicates are
    removed while preserving order.
    """
    candidates: list[Path]
    if explicit:
        candidates = [Path(p).expanduser() for p in explicit]
    else:
        candidates = scan_paths_from_env(env)
        if not candidates:
            candidates = [fallback if fallback is not None else Path.cwd()]

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return ordered


def _read_project_identity(lattice_dir: Path) -> tuple[str | None, str | None, str | None]:
    """Return ``(project_code, project_name, error)`` for a ``.lattice`` dir."""
    config_path = lattice_dir / "config.json"
    try:
        data = json.loads(config_path.read_text())
    except FileNotFoundError:
        return None, None, "config.json missing"
    except json.JSONDecodeError as exc:
        return None, None, f"config.json is not valid JSON: {exc.msg}"
    except OSError as exc:
        return None, None, f"config.json unreadable: {exc.strerror or exc}"
    if not isinstance(data, dict):
        return None, None, "config.json is not an object"
    code = data.get("project_code")
    name = data.get("project_name")
    return (
        code if isinstance(code, str) else None,
        name if isinstance(name, str) else None,
        None,
    )


#: A file that marks a directory tree as holding copies of boards rather than
#: boards in their own right — a backup, an export, a portability snapshot.
#: Placed at or above the copied roots, it keeps mirrors out of a scan without
#: deleting anything.
#:
#: Put it at the top of the *repository*, not inside the mirrored directory:
#: the tools that produce mirrors typically delete and rebuild their output
#: directory on every run, which would take the marker with it.
IGNORE_MARKER = ".latticeignore"

#: Environment variable holding an ``os.pathsep``-separated list of glob
#: patterns for project roots to skip. Use this when the mirror tree cannot
#: hold a marker — because it is regenerated, read-only, or not yours.
LATTICE_SCAN_IGNORE_ENV = "LATTICE_SCAN_IGNORE"


def ignore_patterns_from_env(env: dict[str, str] | None = None) -> list[str]:
    """Return the configured ignore globs, or an empty list when unset."""
    source = os.environ if env is None else env
    raw = source.get(LATTICE_SCAN_IGNORE_ENV)
    if not raw:
        return []
    out: list[str] = []
    for segment in raw.split(os.pathsep):
        segment = segment.strip()
        if segment:
            out.append(os.path.expanduser(segment))
    return out


def resolve_ignore_patterns(
    explicit: list[str] | tuple[str, ...] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Combine explicit ignore globs with those from the environment.

    Unlike the scan paths, these accumulate rather than override: a project
    ignored globally should stay ignored when someone adds one more pattern
    on the command line.
    """
    patterns = [os.path.expanduser(p) for p in (explicit or [])]
    for pattern in ignore_patterns_from_env(env):
        if pattern not in patterns:
            patterns.append(pattern)
    return patterns


def _matches_ignore(root: Path, patterns: list[str]) -> bool:
    """True when *root* matches any ignore glob.

    A pattern is tried against the full path, the directory name, and the path
    with a ``*`` appended, so both ``*/compaii-state/*`` and a plain
    ``compaii-state`` do the obvious thing.
    """
    if not patterns:
        return False
    text = str(root)
    for pattern in patterns:
        if (
            fnmatch(text, pattern)
            or fnmatch(root.name, pattern)
            or fnmatch(text, pattern.rstrip("/") + "/*")
        ):
            return True
    return False


def _has_ignore_marker(directory: Path, ceiling: int = 6) -> bool:
    """True when *directory* or a nearby ancestor is marked as a mirror."""
    current = directory
    for _ in range(ceiling):
        try:
            if (current / IGNORE_MARKER).is_file():
                return True
        except OSError:
            return False
        if current.parent == current:
            break
        current = current.parent
    return False


def _is_derived_board(root: Path, ignore: list[str] | None = None) -> bool:
    """True when *root*'s board is a copy of some other board.

    Two cases, both of which Lattice already treats as non-canonical:

    * **git linked worktrees.** ``find_root`` is worktree-transparent — from
      inside a worktree it jumps to the primary tree, because a worktree's
      ``.lattice/`` is a snapshot taken when the worktree was created. Listing
      it as its own project would contradict that and double-count every task.
    * **directories marked with .latticeignore**, or matching an ignore glob
      from ``--ignore`` / ``$LATTICE_SCAN_IGNORE``, for deliberate mirrors
      such as a backup or portability package that copies boards wholesale.
    """
    from lattice.storage.fs import _git_primary_worktree

    if _matches_ignore(root, ignore or []):
        return True
    if _has_ignore_marker(root):
        return True
    try:
        primary = _git_primary_worktree(root)
    except OSError:
        return False
    return primary is not None and primary != root


def disambiguate_names(roots: list[Path]) -> dict[Path, str]:
    """Map each root to a display name unique across *roots*.

    Starts from the directory name and, for any name claimed by more than one
    root, prepends parent segments until every name is distinct. Roots that
    were already unique keep their plain directory name, so the common case
    stays short and readable.
    """
    names: dict[Path, str] = {root: (root.name or str(root)) for root in roots}

    for _ in range(_MAX_NAME_SEGMENTS):
        clashes: dict[str, list[Path]] = {}
        for root, name in names.items():
            clashes.setdefault(name, []).append(root)
        contested = {name: roots_ for name, roots_ in clashes.items() if len(roots_) > 1}
        if not contested:
            break
        for name, roots_ in contested.items():
            depth = name.count("/") + 1
            for root in roots_:
                parts = root.parts
                if len(parts) <= depth:
                    continue
                names[root] = "/".join(parts[-(depth + 1) :])

    # Any remaining collision (identical trailing paths) falls back to the
    # absolute path, which is unique by construction.
    final: dict[str, list[Path]] = {}
    for root, name in names.items():
        final.setdefault(name, []).append(root)
    for name, roots_ in final.items():
        if len(roots_) > 1:
            for root in roots_:
                names[root] = str(root)
    return names


def discover_projects(
    scan_paths: list[Path],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    ignore: list[str] | None = None,
) -> list[DiscoveredProject]:
    """Find every Lattice project under *scan_paths*.

    The walk is bounded by *max_depth* levels below each search path and skips
    well-known heavy directories. A path that is itself a project root is
    reported, so pointing the scanner directly at one repository works.

    Results are sorted by display name. Projects reachable from more than one
    search path are reported once.

    Unreadable directories are skipped silently — discovery must never fail
    because one subtree has restrictive permissions.
    """
    found: dict[Path, DiscoveredProject] = {}

    def record(root: Path) -> None:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in found:
            return
        lattice_dir = resolved / LATTICE_DIR
        code, name, error = _read_project_identity(lattice_dir)
        found[resolved] = DiscoveredProject(
            root=resolved,
            lattice_dir=lattice_dir,
            name=resolved.name or str(resolved),
            project_code=code,
            project_name=name,
            error=error,
        )

    def walk(directory: Path, depth: int) -> None:
        try:
            is_project = (directory / LATTICE_DIR).is_dir()
        except OSError:
            # Unreadable directory (e.g. mode 000). Nothing to report, and the
            # scan must continue over its siblings.
            return
        if is_project and not _is_derived_board(directory, ignore):
            record(directory)
            # A project root may still contain nested projects (for example a
            # monorepo with per-package boards), so keep descending.
        if depth >= max_depth:
            return
        try:
            entries = list(os.scandir(directory))
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            return
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if entry.name in _SKIP_DIRS or entry.name == LATTICE_DIR:
                continue
            walk(Path(entry.path), depth + 1)

    for base in scan_paths:
        if base.is_dir():
            walk(base, 0)

    display = disambiguate_names(list(found))
    named = [
        DiscoveredProject(
            root=p.root,
            lattice_dir=p.lattice_dir,
            name=display[p.root],
            project_code=p.project_code,
            project_name=p.project_name,
            error=p.error,
        )
        for p in found.values()
    ]
    return sorted(named, key=lambda p: (p.name.lower(), str(p.root)))


#: Task statuses representing work neither finished nor abandoned.
OPEN_STATUSES = frozenset(
    {"backlog", "in_planning", "planned", "in_progress", "review", "blocked", "needs_human"}
)


def summarize_projects(projects: list[DiscoveredProject]) -> list[dict]:
    """Describe each project for the dashboard's picker.

    Reads each board only to count tasks. A project that cannot be read is
    still described, with ``ok`` false and its error — an overview that
    silently omits a broken board claims a completeness it does not have.
    """
    from lattice.core.stats import load_all_snapshots

    out: list[dict] = []
    for project in projects:
        entry: dict = {
            "name": project.name,
            "root": str(project.root),
            "project_code": project.project_code,
            "project_name": project.project_name,
            "task_count": 0,
            "open_count": 0,
            "archived_count": 0,
            "ok": project.error is None,
            "error": project.error,
        }
        if project.error is None:
            try:
                active, archived = load_all_snapshots(project.lattice_dir)
            except Exception as exc:  # noqa: BLE001 - reported as data, not raised
                entry["ok"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
            else:
                entry["task_count"] = len(active)
                entry["archived_count"] = len(archived)
                entry["open_count"] = sum(1 for s in active if s.get("status") in OPEN_STATUSES)
        out.append(entry)
    return out
