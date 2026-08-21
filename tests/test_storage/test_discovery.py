"""Tests for multi-project discovery."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lattice.storage.discovery import (
    IGNORE_MARKER,
    LATTICE_SCAN_IGNORE_ENV,
    LATTICE_SCAN_PATH_ENV,
    DiscoveredProject,
    disambiguate_names,
    discover_projects,
    ignore_patterns_from_env,
    resolve_ignore_patterns,
    resolve_scan_paths,
    scan_paths_from_env,
)
from lattice.storage.fs import LATTICE_DIR


def make_project(root: Path, code: str | None = "TST", name: str | None = None) -> Path:
    """Create a minimal project root with a readable config.json."""
    lattice = root / LATTICE_DIR
    lattice.mkdir(parents=True)
    config: dict = {}
    if code is not None:
        config["project_code"] = code
    if name is not None:
        config["project_name"] = name
    (lattice / "config.json").write_text(json.dumps(config))
    return root


class TestScanPathsFromEnv:
    def test_unset_returns_empty(self) -> None:
        assert scan_paths_from_env({}) == []

    def test_empty_string_returns_empty(self) -> None:
        assert scan_paths_from_env({LATTICE_SCAN_PATH_ENV: ""}) == []

    def test_single_path(self) -> None:
        result = scan_paths_from_env({LATTICE_SCAN_PATH_ENV: "/a/b"})
        assert result == [Path("/a/b")]

    def test_multiple_paths_split_on_pathsep(self) -> None:
        raw = os.pathsep.join(["/a", "/b", "/c"])
        result = scan_paths_from_env({LATTICE_SCAN_PATH_ENV: raw})
        assert result == [Path("/a"), Path("/b"), Path("/c")]

    def test_blank_segments_ignored(self) -> None:
        raw = os.pathsep.join(["/a", "", "/b", "  "])
        result = scan_paths_from_env({LATTICE_SCAN_PATH_ENV: raw})
        assert result == [Path("/a"), Path("/b")]

    def test_tilde_is_expanded(self) -> None:
        result = scan_paths_from_env({LATTICE_SCAN_PATH_ENV: "~/somewhere"})
        assert result == [Path.home() / "somewhere"]


class TestResolveScanPaths:
    def test_explicit_wins_over_env(self, tmp_path: Path) -> None:
        env = {LATTICE_SCAN_PATH_ENV: str(tmp_path / "from_env")}
        result = resolve_scan_paths([str(tmp_path / "explicit")], env=env)
        assert result == [(tmp_path / "explicit").resolve()]

    def test_env_wins_over_fallback(self, tmp_path: Path) -> None:
        env = {LATTICE_SCAN_PATH_ENV: str(tmp_path / "from_env")}
        result = resolve_scan_paths(None, env=env, fallback=tmp_path / "fb")
        assert result == [(tmp_path / "from_env").resolve()]

    def test_fallback_used_when_nothing_set(self, tmp_path: Path) -> None:
        result = resolve_scan_paths(None, env={}, fallback=tmp_path)
        assert result == [tmp_path.resolve()]

    def test_duplicates_removed_preserving_order(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        result = resolve_scan_paths([str(a), str(b), str(a)], env={})
        assert result == [a.resolve(), b.resolve()]


class TestDisambiguateNames:
    def test_unique_names_stay_plain(self) -> None:
        roots = [Path("/x/alpha"), Path("/y/beta")]
        assert disambiguate_names(roots) == {
            Path("/x/alpha"): "alpha",
            Path("/y/beta"): "beta",
        }

    def test_collision_gains_parent_segment(self) -> None:
        roots = [Path("/x/dup"), Path("/y/dup")]
        names = disambiguate_names(roots)
        assert names[Path("/x/dup")] == "x/dup"
        assert names[Path("/y/dup")] == "y/dup"
        assert len(set(names.values())) == 2

    def test_only_colliding_names_are_lengthened(self) -> None:
        roots = [Path("/x/dup"), Path("/y/dup"), Path("/z/solo")]
        names = disambiguate_names(roots)
        assert names[Path("/z/solo")] == "solo"

    def test_deep_collision_resolves(self) -> None:
        roots = [Path("/a/p/dup"), Path("/b/p/dup")]
        names = disambiguate_names(roots)
        assert len(set(names.values())) == 2

    def test_empty_input(self) -> None:
        assert disambiguate_names([]) == {}


class TestDiscoverProjects:
    def test_finds_project_at_scan_root(self, tmp_path: Path) -> None:
        make_project(tmp_path / "proj")
        found = discover_projects([tmp_path])
        assert [p.name for p in found] == ["proj"]

    def test_scan_path_that_is_itself_a_project(self, tmp_path: Path) -> None:
        make_project(tmp_path)
        found = discover_projects([tmp_path])
        assert len(found) == 1
        assert found[0].root == tmp_path.resolve()

    def test_reads_project_code_and_name(self, tmp_path: Path) -> None:
        make_project(tmp_path / "proj", code="ABC", name="Alpha Beta")
        found = discover_projects([tmp_path])
        assert found[0].project_code == "ABC"
        assert found[0].project_name == "Alpha Beta"
        assert found[0].error is None

    def test_nested_project_within_depth(self, tmp_path: Path) -> None:
        make_project(tmp_path / "a" / "b" / "deep")
        found = discover_projects([tmp_path], max_depth=3)
        assert [p.name for p in found] == ["deep"]

    def test_project_beyond_depth_is_not_found(self, tmp_path: Path) -> None:
        make_project(tmp_path / "a" / "b" / "c" / "d" / "toodeep")
        found = discover_projects([tmp_path], max_depth=2)
        assert found == []

    def test_skips_heavy_directories(self, tmp_path: Path) -> None:
        make_project(tmp_path / "node_modules" / "pkg")
        make_project(tmp_path / "real")
        found = discover_projects([tmp_path])
        assert [p.name for p in found] == ["real"]

    def test_missing_config_is_reported_not_dropped(self, tmp_path: Path) -> None:
        (tmp_path / "broken" / LATTICE_DIR).mkdir(parents=True)
        found = discover_projects([tmp_path])
        assert len(found) == 1
        assert found[0].error == "config.json missing"
        assert found[0].project_code is None

    def test_malformed_config_is_reported(self, tmp_path: Path) -> None:
        lattice = tmp_path / "bad" / LATTICE_DIR
        lattice.mkdir(parents=True)
        (lattice / "config.json").write_text("{not json")
        found = discover_projects([tmp_path])
        assert found[0].error is not None
        assert "not valid JSON" in found[0].error

    def test_nonexistent_scan_path_is_skipped(self, tmp_path: Path) -> None:
        assert discover_projects([tmp_path / "missing"]) == []

    def test_same_project_via_two_scan_paths_reported_once(self, tmp_path: Path) -> None:
        make_project(tmp_path / "proj")
        found = discover_projects([tmp_path, tmp_path / "proj"])
        assert len(found) == 1

    def test_duplicate_names_are_disambiguated(self, tmp_path: Path) -> None:
        make_project(tmp_path / "x" / "same")
        make_project(tmp_path / "y" / "same")
        found = discover_projects([tmp_path])
        names = {p.name for p in found}
        assert names == {"x/same", "y/same"}

    def test_results_are_sorted_and_stable(self, tmp_path: Path) -> None:
        for n in ("zeta", "alpha", "mid"):
            make_project(tmp_path / n)
        first = [p.name for p in discover_projects([tmp_path])]
        second = [p.name for p in discover_projects([tmp_path])]
        assert first == ["alpha", "mid", "zeta"]
        assert first == second

    def test_symlinked_directory_is_not_followed(self, tmp_path: Path) -> None:
        make_project(tmp_path / "real")
        link = tmp_path / "link"
        try:
            link.symlink_to(tmp_path / "real", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")
        found = discover_projects([tmp_path])
        assert [p.name for p in found] == ["real"]

    def test_unreadable_directory_does_not_abort_scan(self, tmp_path: Path) -> None:
        if os.geteuid() == 0:
            pytest.skip("root bypasses permission checks")
        make_project(tmp_path / "visible")
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o000)
        try:
            found = discover_projects([tmp_path])
            assert "visible" in [p.name for p in found]
        finally:
            locked.chmod(0o755)


class TestDiscoveredProjectShape:
    def test_lattice_dir_points_inside_root(self, tmp_path: Path) -> None:
        make_project(tmp_path / "proj")
        found = discover_projects([tmp_path])[0]
        assert found.lattice_dir == found.root / LATTICE_DIR

    def test_is_frozen(self, tmp_path: Path) -> None:
        p = DiscoveredProject(root=tmp_path, lattice_dir=tmp_path / LATTICE_DIR, name="x")
        with pytest.raises(Exception):
            p.name = "y"  # type: ignore[misc]


class TestDerivedBoards:
    """Copies of a board are not projects in their own right."""

    def test_git_worktree_board_is_skipped(self, tmp_path: Path) -> None:
        # Primary repo with a board.
        primary = tmp_path / "repo"
        make_project(primary)
        (primary / ".git").mkdir()
        (primary / ".git" / "worktrees").mkdir()
        (primary / ".git" / "worktrees" / "wt").mkdir()

        # Linked worktree carrying the snapshot git checked out with it.
        wt = tmp_path / "repo-feature"
        make_project(wt)
        (wt / ".git").write_text(f"gitdir: {primary / '.git' / 'worktrees' / 'wt'}\n")

        found = discover_projects([tmp_path])
        assert [p.name for p in found] == ["repo"], "worktree board must not be its own project"

    def test_primary_worktree_is_still_found(self, tmp_path: Path) -> None:
        primary = tmp_path / "repo"
        make_project(primary)
        (primary / ".git").mkdir()
        assert [p.name for p in discover_projects([tmp_path])] == ["repo"]

    def test_latticeignore_excludes_a_mirror(self, tmp_path: Path) -> None:
        make_project(tmp_path / "live")
        mirror = tmp_path / "backup"
        make_project(mirror / "live")
        (mirror / ".latticeignore").touch()
        found = discover_projects([tmp_path])
        assert [p.name for p in found] == ["live"]

    def test_latticeignore_applies_to_nested_copies(self, tmp_path: Path) -> None:
        mirror = tmp_path / "snapshot"
        (mirror).mkdir()
        (mirror / ".latticeignore").touch()
        make_project(mirror / "projects" / "a")
        make_project(mirror / "projects" / "b")
        assert discover_projects([tmp_path]) == []

    def test_marker_in_the_board_root_itself(self, tmp_path: Path) -> None:
        root = tmp_path / "copy"
        make_project(root)
        (root / ".latticeignore").touch()
        assert discover_projects([tmp_path]) == []

    def test_non_git_tree_unaffected(self, tmp_path: Path) -> None:
        make_project(tmp_path / "plain")
        assert [p.name for p in discover_projects([tmp_path])] == ["plain"]


class TestIgnorePatterns:
    """Central ignore list, for mirrors that cannot hold a marker file."""

    def test_env_unset_returns_empty(self) -> None:
        assert ignore_patterns_from_env({}) == []

    def test_env_splits_on_pathsep(self) -> None:
        raw = os.pathsep.join(["*/mirror/*", "backup"])
        assert ignore_patterns_from_env({LATTICE_SCAN_IGNORE_ENV: raw}) == ["*/mirror/*", "backup"]

    def test_explicit_and_env_accumulate(self) -> None:
        env = {LATTICE_SCAN_IGNORE_ENV: "from-env"}
        assert resolve_ignore_patterns(["from-flag"], env=env) == ["from-flag", "from-env"]

    def test_duplicates_collapse(self) -> None:
        env = {LATTICE_SCAN_IGNORE_ENV: "same"}
        assert resolve_ignore_patterns(["same"], env=env) == ["same"]

    def test_ignore_by_bare_directory_name(self, tmp_path: Path) -> None:
        make_project(tmp_path / "keep")
        make_project(tmp_path / "drop")
        found = discover_projects([tmp_path], ignore=["drop"])
        assert [p.name for p in found] == ["keep"]

    def test_ignore_by_glob_prefix(self, tmp_path: Path) -> None:
        make_project(tmp_path / "keep")
        make_project(tmp_path / "mirror" / "a")
        make_project(tmp_path / "mirror" / "b")
        found = discover_projects([tmp_path], ignore=[str(tmp_path / "mirror")])
        assert [p.name for p in found] == ["keep"]

    def test_ignore_by_wildcard(self, tmp_path: Path) -> None:
        make_project(tmp_path / "live-state")
        make_project(tmp_path / "keep")
        found = discover_projects([tmp_path], ignore=["*-state"])
        assert [p.name for p in found] == ["keep"]

    def test_no_patterns_ignores_nothing(self, tmp_path: Path) -> None:
        make_project(tmp_path / "a")
        assert len(discover_projects([tmp_path], ignore=[])) == 1

    def test_marker_survives_where_a_nested_one_would_not(self, tmp_path: Path) -> None:
        # A marker at the repo root still covers boards nested below it, which
        # is why it belongs there rather than inside a regenerated subdir.
        repo = tmp_path / "state-repo"
        (repo).mkdir()
        (repo / IGNORE_MARKER).touch()
        make_project(repo / "projects" / "mirrored")
        make_project(tmp_path / "real")
        assert [p.name for p in discover_projects([tmp_path])] == ["real"]
