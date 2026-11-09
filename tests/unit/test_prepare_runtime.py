import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "deployment" / "installer" / "prepare_runtime.py"
spec = importlib.util.spec_from_file_location("stunsail_prepare_runtime", MODULE)
assert spec and spec.loader
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def source_dir(tmp_path):
    source = tmp_path / "source"
    for path in runtime.REQUIRED_SOURCE:
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("test", encoding="utf-8")
    return source


def test_prepares_new_runtime_using_locked_dependencies(tmp_path, monkeypatch):
    source = source_dir(tmp_path)
    target = tmp_path / "release"
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/tools/uv")
    monkeypatch.setenv("VIRTUAL_ENV", "other-venv")
    calls = []

    def run(command, *, cwd, env, check):
        calls.append((command, cwd, env, check))
        bin_dir = target / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        for name in ("python", "uvicorn", "stunsail-agent", "alembic"):
            executable = bin_dir / name
            executable.write_text("test")
            executable.chmod(0o755)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    runtime.prepare(source, target)
    command, cwd, env, check = calls[0]
    assert command == [
        "/tools/uv",
        "sync",
        "--locked",
        "--all-packages",
        "--no-default-groups",
        "--group",
        "runtime",
    ]
    assert cwd == target and check
    assert "VIRTUAL_ENV" not in env
    assert env["UV_PROJECT_ENVIRONMENT"] == str(target / ".venv")
    assert (target / "apps/web/dist/index.html").is_file()
    assert not (source / ".venv").exists()


def test_refuses_existing_destination_and_missing_uv(tmp_path, monkeypatch):
    source = source_dir(tmp_path)
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "important"
    marker.write_text("unchanged")
    with pytest.raises(FileExistsError):
        runtime.prepare(source, target)
    assert marker.read_text() == "unchanged"
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="uv is required"):
        runtime.prepare(source, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_refuses_nested_destination_and_invalid_source(tmp_path, monkeypatch):
    source = source_dir(tmp_path)
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "uv")
    with pytest.raises(ValueError, match="must not contain"):
        runtime.prepare(source, source / "new")
    (source / "uv.lock").unlink()
    with pytest.raises(ValueError, match="missing a regular file"):
        runtime.prepare(source, tmp_path / "new")


@pytest.mark.skipif(os.name == "nt", reason="symlink creation may require Windows privileges")
def test_refuses_symlink_inputs(tmp_path, monkeypatch):
    source = source_dir(tmp_path)
    (source / "linked").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "uv")
    with pytest.raises(ValueError, match="contains symlink"):
        runtime.prepare(source, tmp_path / "new")


def test_failure_leaves_partial_runtime_for_explicit_inspection(tmp_path, monkeypatch):
    source = source_dir(tmp_path)
    target = tmp_path / "release"
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "uv")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["uv", "sync"])

    monkeypatch.setattr(runtime.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        runtime.prepare(source, target)
    assert (target / "pyproject.toml").is_file()
