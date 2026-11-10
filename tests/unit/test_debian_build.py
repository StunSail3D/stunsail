import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "deployment" / "debian" / "build_package.py"
spec = importlib.util.spec_from_file_location("stunsail_debian_build", MODULE)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def create_source(root):
    def write(path, content="content"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    write("pyproject.toml", '[project]\nversion = "0.1.0"\n')
    write("uv.lock")
    write("alembic.ini")
    for package in builder.PACKAGES:
        write(f"{package}/pyproject.toml")
        write(f"{package}/src/module/__init__.py", "")
        write(f"{package}/src/module/.secret.py", "private")
        write(f"{package}/src/module/cache.db", "private")
    write("database/migrations/env.py", "")
    write("database/migrations/versions/0001.py", "")
    write("apps/web/dist/index.html", "<html></html>")
    write("apps/web/dist/assets/app.js", "")
    write("apps/web/dist/spools/red.png", "")
    for name in (
        "add_agent.py",
        "agent_runtime_smoke.py",
        "apply_restore.py",
        "apply_upgrade.py",
        "backup_installation.py",
        "check_running.py",
        "configure.py",
        "guided_install.py",
        "install_fresh.py",
        "maintenance_backup.py",
        "preflight.py",
        "prepare_runtime.py",
        "register_local_agent.py",
        "rehearse_upgrade.py",
        "release_fingerprint.py",
        "remove_services.py",
        "rollback_upgrade.py",
        "runtime_smoke.py",
        "sqlite_snapshot.py",
        "stage_restore.py",
        "verify_backup.py",
        "verify_release.py",
        "README.md",
    ):
        write(f"deployment/installer/{name}")
    for name in ("stunsail-core.service", "stunsail-agent@.service", "README.md"):
        write(f"deployment/systemd/{name}")
    write("docs/architecture/operations.md")
    write(".env", "secret")
    write("data/private.db", "private")
    write("deployment/installer/configs/agent.yaml", "private")


def test_staging_includes_only_explicit_release_inputs(tmp_path):
    root = tmp_path / "source"
    create_source(root)
    stage = tmp_path / "stage"
    assert builder.stage_payload(root, stage) == "0.1.0"
    release = stage / "usr" / "share" / "stunsail" / "source"
    assert (release / "database/migrations/versions/0001.py").is_file()
    assert (release / "apps/web/dist/assets/app.js").is_file()
    assert (release / "apps/web/dist/spools/red.png").is_file()
    assert (release / "docs/architecture/operations.md").is_file()
    assert not (release / ".env").exists()
    assert not (release / "data").exists()
    assert not (release / "deployment/installer/configs").exists()
    assert not list(release.rglob("cache.db"))
    assert not list(release.rglob(".secret.py"))
    control = (stage / "DEBIAN" / "control").read_text()
    assert "Version: 0.1.0-1" in control
    assert not (stage / "DEBIAN" / "postinst").exists()


def test_missing_web_assets_fails_instead_of_building_broken_package(tmp_path):
    root = tmp_path / "source"
    create_source(root)
    (root / "apps/web/dist/index.html").unlink()
    with pytest.raises(ValueError, match="required regular file missing"):
        builder.stage_payload(root, tmp_path / "stage")


def test_invalid_version_is_rejected(tmp_path):
    root = tmp_path / "source"
    create_source(root)
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.0\\nInjected: value"\n')
    with pytest.raises(ValueError, match="project version"):
        builder.stage_payload(root, tmp_path / "stage")


def test_existing_package_output_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(builder.shutil, "which", lambda _: "dpkg-deb")
    target = tmp_path / "package.deb"
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        builder.build(tmp_path, target)
    assert target.read_bytes() == b"existing"
