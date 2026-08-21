"""Tests for the dashboard's project-scope filter.

The scope turns the single-project dashboard into a multi-project one: the
same endpoints, the same UI, pointed at whichever project the request names.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lattice.dashboard.server import Scope, create_server


def make_project(root: Path, code: str) -> Path:
    from lattice.core.config import default_config, serialize_config
    from lattice.storage.fs import LATTICE_DIR, atomic_write, ensure_lattice_dirs

    ensure_lattice_dirs(root)
    cfg = default_config()
    cfg["project_code"] = code
    cfg["auto_code_review_on_transition"] = False
    cfg["auto_plan_review_on_transition"] = False
    atomic_write(root / LATTICE_DIR / "config.json", serialize_config(cfg))
    (root / LATTICE_DIR / "events" / "_lifecycle.jsonl").touch()
    return root


def create_task(root: Path, title: str, *extra: str) -> dict:
    from click.testing import CliRunner

    from lattice.cli.main import cli

    args = ["create", title, "--actor", "human:test", "--json", *extra]
    result = CliRunner().invoke(cli, args, env={"LATTICE_ROOT": str(root)})
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Two projects with different task counts, so responses are telling apart."""
    make_project(tmp_path / "alpha", "ALP")
    make_project(tmp_path / "beta", "BET")
    create_task(tmp_path / "alpha", "alpha one")
    create_task(tmp_path / "alpha", "alpha two")
    create_task(tmp_path / "beta", "beta only")
    return tmp_path


def serve(lattice_dir: Path, scope: Scope | None):
    server = create_server(lattice_dir, "127.0.0.1", 0, scope=scope)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{port}"


@pytest.fixture()
def scoped(workspace: Path):
    scope = Scope([workspace], max_depth=3)
    server, thread, url = serve(workspace / "alpha" / ".lattice", scope)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def unscoped(workspace: Path):
    server, thread, url = serve(workspace / "alpha" / ".lattice", None)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


class TestScopeDisabled:
    """Without a scope the dashboard must behave exactly as it did before."""

    def test_scope_reports_disabled(self, unscoped: str) -> None:
        assert get(f"{unscoped}/api/scope")["data"]["enabled"] is False

    def test_tasks_still_served(self, unscoped: str) -> None:
        assert len(get(f"{unscoped}/api/tasks")["data"]) == 2

    def test_project_param_is_ignored(self, unscoped: str) -> None:
        # No scope means no switching: the param must not redirect anything.
        assert len(get(f"{unscoped}/api/tasks?project=beta")["data"]) == 2


class TestScopeEnabled:
    def test_scope_lists_projects(self, scoped: str) -> None:
        data = get(f"{scoped}/api/scope")["data"]
        assert data["enabled"] is True
        assert {p["name"] for p in data["projects"]} == {"alpha", "beta"}

    def test_default_is_the_startup_project(self, scoped: str) -> None:
        assert get(f"{scoped}/api/scope")["data"]["default"] == "alpha"

    def test_no_param_serves_default_project(self, scoped: str) -> None:
        assert len(get(f"{scoped}/api/tasks")["data"]) == 2

    def test_param_switches_project(self, scoped: str) -> None:
        tasks = get(f"{scoped}/api/tasks?project=beta")["data"]
        assert len(tasks) == 1
        assert tasks[0]["title"] == "beta only"

    def test_explicit_default_sentinel(self, scoped: str) -> None:
        assert len(get(f"{scoped}/api/tasks?project=__default__")["data"]) == 2

    def test_stats_follow_the_selected_project(self, scoped: str) -> None:
        alpha = get(f"{scoped}/api/stats?project=alpha")["data"]
        beta = get(f"{scoped}/api/stats?project=beta")["data"]
        assert alpha["by_status"] != beta["by_status"]

    def test_config_follows_the_selected_project(self, scoped: str) -> None:
        assert get(f"{scoped}/api/config?project=beta")["data"]["project_code"] == "BET"

    def test_activity_endpoint_accepts_scope(self, scoped: str) -> None:
        assert get(f"{scoped}/api/activity?project=beta")["ok"] is True

    def test_graph_endpoint_accepts_scope(self, scoped: str) -> None:
        assert get(f"{scoped}/api/graph?project=beta")["ok"] is True

    def test_task_detail_resolves_within_selected_project(self, scoped: str) -> None:
        tasks = get(f"{scoped}/api/tasks?project=beta")["data"]
        detail = get(f"{scoped}/api/tasks/{tasks[0]['id']}?project=beta")
        assert detail["ok"] is True
        assert detail["data"]["title"] == "beta only"

    def test_unknown_project_is_refused(self, scoped: str) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(f"{scoped}/api/tasks?project=ghost")
        assert exc.value.code == 404

    def test_scope_survives_a_new_project_appearing(self, scoped: str, workspace: Path) -> None:
        make_project(workspace / "gamma", "GAM")
        # Discovery is cached briefly; force past the TTL.
        Scope.TTL_SECONDS = 0.0
        try:
            names = {p["name"] for p in get(f"{scoped}/api/scope")["data"]["projects"]}
            assert "gamma" in names
        finally:
            Scope.TTL_SECONDS = 5.0


class TestScopeUnit:
    def test_by_name_finds_project(self, workspace: Path) -> None:
        scope = Scope([workspace])
        assert scope.by_name("alpha") is not None

    def test_by_name_returns_none_for_unknown(self, workspace: Path) -> None:
        assert Scope([workspace]).by_name("nope") is None

    def test_projects_are_cached(self, workspace: Path) -> None:
        scope = Scope([workspace])
        assert scope.projects() is scope.projects()


class TestAllMode:
    """`?project=__all__` merges every project in scope."""

    def test_tasks_are_merged(self, scoped: str) -> None:
        rows = get(f"{scoped}/api/tasks?project=__all__")["data"]
        assert len(rows) == 3
        assert {r["project"] for r in rows} == {"alpha", "beta"}

    def test_every_row_carries_provenance(self, scoped: str) -> None:
        for row in get(f"{scoped}/api/tasks?project=__all__")["data"]:
            assert row["project"]
            assert row["project_root"]
            assert "project_code" in row

    def test_stats_are_summed(self, scoped: str) -> None:
        stats = get(f"{scoped}/api/stats?project=__all__")["data"]
        # Same shape as a single-project response: (name, count) pairs.
        assert sum(count for _, count in stats["by_status"]) == 3
        assert stats["summary"]["total_tasks"] == 3
        assert stats["projects"] == 2

    def test_stats_shape_matches_single_project(self, scoped: str) -> None:
        one = get(f"{scoped}/api/stats?project=alpha")["data"]
        allm = get(f"{scoped}/api/stats?project=__all__")["data"]
        for key in ("by_status", "by_priority", "by_type", "wip", "busiest"):
            assert isinstance(allm[key], type(one[key])), key
        for key in ("summary", "blocked"):
            assert isinstance(allm[key], dict), key

    def test_config_reports_aggregate(self, scoped: str) -> None:
        cfg = get(f"{scoped}/api/config?project=__all__")["data"]
        assert cfg["aggregate"] is True
        assert cfg["project_code"] == "ALL"
        assert cfg["workflow"]["statuses"]

    def test_config_reports_no_conflict_for_matching_workflows(self, scoped: str) -> None:
        cfg = get(f"{scoped}/api/config?project=__all__")["data"]
        assert cfg["workflow_conflicts"] == []

    def test_scope_advertises_the_sentinel(self, scoped: str) -> None:
        assert get(f"{scoped}/api/scope")["data"]["all_sentinel"] == "__all__"

    def test_archived_merges(self, scoped: str) -> None:
        assert get(f"{scoped}/api/archived?project=__all__")["ok"] is True

    def test_create_is_refused_in_all_mode(self, scoped: str) -> None:
        req = urllib.request.Request(
            f"{scoped}/api/tasks?project=__all__",
            data=json.dumps({"title": "nope", "actor": "human:test"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=10)
        assert exc.value.code == 400
        assert "PROJECT_REQUIRED" in exc.value.read().decode()

    def test_card_action_with_explicit_project_still_works(self, scoped: str) -> None:
        # This is how the UI acts on a card in ALL mode: it posts the card's
        # own project, so the request is an ordinary single-project write.
        task = get(f"{scoped}/api/tasks?project=beta")["data"][0]
        req = urllib.request.Request(
            f"{scoped}/api/tasks/{task['id']}/status?project=beta",
            data=json.dumps({"status": "planned", "actor": "human:test"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert json.loads(resp.read())["ok"] is True
        assert get(f"{scoped}/api/tasks?project=beta")["data"][0]["status"] == "planned"

    def test_no_duplicate_marker_when_boards_are_distinct(self, scoped: str) -> None:
        for row in get(f"{scoped}/api/tasks?project=__all__")["data"]:
            assert "duplicate_in" not in row


class TestAllModeDuplicates:
    """Copied .lattice directories are surfaced, not hidden."""

    @pytest.fixture()
    def with_copy(self, workspace: Path):
        import shutil

        shutil.copytree(workspace / "alpha", workspace / "alpha-copy")
        scope = Scope([workspace], max_depth=3)
        server, thread, url = serve(workspace / "alpha" / ".lattice", scope)
        try:
            yield url
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_duplicated_tasks_appear_twice(self, with_copy: str) -> None:
        rows = get(f"{with_copy}/api/tasks?project=__all__")["data"]
        ids = [r["id"] for r in rows]
        assert len(ids) != len(set(ids)), "copies must not be silently deduplicated"

    def test_duplicates_are_marked_with_the_other_board(self, with_copy: str) -> None:
        rows = get(f"{with_copy}/api/tasks?project=__all__")["data"]
        marked = [r for r in rows if r.get("duplicate_in")]
        assert marked, "duplicated rows must be flagged"
        for row in marked:
            assert row["project"] not in row["duplicate_in"]
            assert all(isinstance(name, str) for name in row["duplicate_in"])
