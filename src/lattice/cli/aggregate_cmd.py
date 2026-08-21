"""``lattice aggregate`` — the dashboard across every project.

Lattice keeps one board per project so task state travels with the code. That
leaves no single place to see work spanning several repositories.

``lattice dashboard`` serves one project. ``lattice aggregate`` serves the same
dashboard with a project picker: the whole UI — board, graph, activity, task
detail, and writes — follows whichever project is selected, and "All projects"
merges them into one board.

It does not require the current directory to be a Lattice project.
"""

from __future__ import annotations

import errno
import json
import socket
import sys
from pathlib import Path

import click

from lattice.cli.main import cli
from lattice.completion import complete_project_name
from lattice.storage.discovery import (
    DEFAULT_MAX_DEPTH,
    LATTICE_SCAN_IGNORE_ENV,
    LATTICE_SCAN_PATH_ENV,
    discover_projects,
    resolve_ignore_patterns,
    resolve_scan_paths,
    summarize_projects,
)

_DEFAULT_PORT = 8800


def _find_free_port(host: str, near: int) -> int | None:
    for candidate in range(near + 1, near + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, candidate))
                return candidate
        except OSError:
            continue
    return None


@cli.command("aggregate")
@click.option(
    "--path",
    "paths",
    multiple=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help=(
        f"Directory to scan for projects (repeatable). "
        f"Defaults to ${LATTICE_SCAN_PATH_ENV}, then the current directory."
    ),
)
@click.option(
    "--ignore",
    "ignore_globs",
    multiple=True,
    shell_complete=complete_project_name,
    help=(
        f"Glob for project roots to skip, such as a mirror or backup tree "
        f"(repeatable). Adds to ${LATTICE_SCAN_IGNORE_ENV}."
    ),
)
@click.option(
    "--depth",
    default=DEFAULT_MAX_DEPTH,
    show_default=True,
    type=int,
    help="How many levels below each scan path to search.",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
@click.option(
    "--port", default=_DEFAULT_PORT, show_default=True, type=int, help="Port to bind to."
)
@click.option("--list-projects", is_flag=True, help="List the projects found and exit.")
@click.option("--json", "output_json", is_flag=True, help="Output structured JSON.")
def aggregate_cmd(
    paths: tuple[str, ...],
    ignore_globs: tuple[str, ...],
    depth: int,
    host: str,
    port: int,
    list_projects: bool,
    output_json: bool,
) -> None:
    """Serve the dashboard over every project under the scan paths."""
    scan_paths = resolve_scan_paths(list(paths) or None)
    ignore = resolve_ignore_patterns(list(ignore_globs) or None)
    projects = discover_projects(scan_paths, max_depth=depth, ignore=ignore)

    if list_projects:
        _list(projects, scan_paths, output_json)
        return

    readable = [p for p in projects if p.error is None]
    if not readable:
        where = ", ".join(str(p) for p in scan_paths)
        msg = f"No readable Lattice projects found under: {where}"
        if output_json:
            click.echo(json.dumps({"ok": False, "error": {"code": "NO_PROJECTS", "message": msg}}))
        else:
            click.echo(msg, err=True)
        sys.exit(1)

    _serve(readable[0].lattice_dir, scan_paths, ignore, depth, host, port, output_json)


def _list(projects: list, scan_paths: list[Path], output_json: bool) -> None:
    summaries = summarize_projects(projects)
    if output_json:
        click.echo(
            json.dumps(
                {
                    "ok": True,
                    "data": {"scan_paths": [str(p) for p in scan_paths], "projects": summaries},
                },
                indent=2,
                default=str,
            )
        )
        return
    if not summaries:
        click.echo(f"No Lattice projects found under: {', '.join(str(p) for p in scan_paths)}")
        return
    click.echo(f"Lattice projects ({len(summaries)}):\n")
    for entry in summaries:
        code = f"[{entry['project_code']}]" if entry["project_code"] else "[--]"
        if not entry["ok"]:
            click.echo(f"  {entry['name']:<28} {code:<8} ERROR: {entry['error']}")
        else:
            click.echo(
                f"  {entry['name']:<28} {code:<8} "
                f"{entry['open_count']:>4} open / {entry['task_count']:>4} tasks   {entry['root']}"
            )


def _serve(
    default_dir: Path,
    scan_paths: list[Path],
    ignore: list[str],
    depth: int,
    host: str,
    port: int,
    output_json: bool,
) -> None:
    from lattice.dashboard.server import Scope, create_server

    scope = Scope(scan_paths, max_depth=depth, ignore=ignore)
    try:
        server = create_server(default_dir, host, port, scope=scope)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            alt = _find_free_port(host, port)
            hint = f"  lattice aggregate --port {alt}" if alt else "  (choose another port)"
            msg = f"Port {port} is already in use.\n{hint}"
        else:
            msg = f"Failed to bind {host}:{port}: {exc}"
        if output_json:
            click.echo(json.dumps({"ok": False, "error": {"code": "BIND_FAILED", "message": msg}}))
        else:
            click.echo(msg, err=True)
        sys.exit(1)

    click.echo(f"Lattice aggregate — {len(scope.projects())} projects")
    for path in scan_paths:
        click.echo(f"  scanning: {path}")
    click.echo(f"\n  http://{host}:{port}/\n\nCtrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    finally:
        server.server_close()
