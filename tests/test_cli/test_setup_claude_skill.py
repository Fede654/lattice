"""Tests for `lattice setup-claude-skill`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lattice.cli.main import cli


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _run(*args: str):
    return CliRunner().invoke(cli, ["setup-claude-skill", *args])


def test_installs_skill_to_claude_skills_dir(home: Path) -> None:
    result = _run("--no-hook")
    assert result.exit_code == 0, result.output
    dest = home / ".claude" / "skills" / "lattice"
    assert (dest / "SKILL.md").exists()
    assert (dest / "references" / "multi-agent-guide.md").exists()
    assert (dest / "scripts" / "session-start.sh").exists()
    assert "Installed" in result.output


def test_rerun_is_a_noop_when_up_to_date(home: Path) -> None:
    _run("--no-hook")
    result = _run("--no-hook")
    assert result.exit_code == 0
    assert "Up to date" in result.output


def test_rerun_refreshes_a_stale_copy(home: Path) -> None:
    _run("--no-hook")
    dest = home / ".claude" / "skills" / "lattice"
    (dest / "SKILL.md").write_text("old release", encoding="utf-8")
    (dest / "leftover.md").write_text("from an older release", encoding="utf-8")

    result = _run("--no-hook")
    assert result.exit_code == 0
    assert "Updated" in result.output
    assert "old release" not in (dest / "SKILL.md").read_text(encoding="utf-8")
    assert not (dest / "leftover.md").exists(), "stale files must not survive a refresh"


def test_force_is_accepted_for_compatibility(home: Path) -> None:
    assert _run("--force", "--no-hook").exit_code == 0


def test_excludes_python_artifacts(home: Path) -> None:
    _run("--no-hook")
    dest = home / ".claude" / "skills" / "lattice"
    assert not (dest / "__init__.py").exists()
    assert not list(dest.rglob("__pycache__"))


def test_scripts_are_executable(home: Path) -> None:
    _run("--no-hook")
    scripts = home / ".claude" / "skills" / "lattice" / "scripts"
    for script in scripts.glob("*.sh"):
        assert script.stat().st_mode & 0o111, script


class TestSessionHook:
    def test_registers_hook_in_settings(self, home: Path) -> None:
        result = _run()
        assert result.exit_code == 0, result.output
        settings = json.loads((home / ".claude" / "settings.json").read_text())
        [entry] = settings["hooks"]["SessionStart"]
        [hook] = entry["hooks"]
        assert hook["type"] == "command"
        assert hook["command"].startswith(
            str(home / ".claude" / "skills" / "lattice" / "scripts" / "session-start.sh")
        )
        assert "Registered the SessionStart hook" in result.output

    def test_preserves_existing_settings(self, home: Path) -> None:
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(
            json.dumps(
                {
                    "permissions": {"allow": ["Bash(git:*)"]},
                    "hooks": {
                        "SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]
                    },
                }
            )
        )
        _run()
        data = json.loads(settings.read_text())
        assert data["permissions"] == {"allow": ["Bash(git:*)"]}
        commands = [h["command"] for e in data["hooks"]["SessionStart"] for h in e["hooks"]]
        assert commands[0] == "echo hi"
        assert len(commands) == 2

    def test_rerun_does_not_duplicate(self, home: Path) -> None:
        _run()
        result = _run()
        assert "already registered" in result.output
        data = json.loads((home / ".claude" / "settings.json").read_text())
        assert len(data["hooks"]["SessionStart"]) == 1

    def test_no_hook_leaves_settings_alone(self, home: Path) -> None:
        _run("--no-hook")
        assert not (home / ".claude" / "settings.json").exists()

    def test_repo_install_never_touches_settings(self, home: Path, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _run("--repo", "--path", str(repo))
        assert result.exit_code == 0, result.output
        assert (repo / ".claude" / "skills" / "lattice" / "SKILL.md").exists()
        assert not (home / ".claude" / "settings.json").exists()

    def test_unreadable_settings_is_reported_not_fatal(self, home: Path) -> None:
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text("{not json")
        result = _run()
        assert result.exit_code == 0
        assert "Could not register" in result.output
        assert settings.read_text() == "{not json"
