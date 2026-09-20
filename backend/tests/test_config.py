from __future__ import annotations

import os
from pathlib import Path

from app.config import load_local_env


def test_local_env_loader_reads_ignored_locations_without_overriding_shell(tmp_path: Path, monkeypatch):
    root = tmp_path
    backend = root / "backend"
    backend.mkdir()
    (root / ".env").write_text(
        "GEMINI_API_KEY=root-secret\nGEMINI_MODEL=root-model # local default\nIGNORED KEY=bad\n",
        encoding="utf-8",
    )
    (backend / ".env").write_text(
        "export GEMINI_API_KEY=backend-secret\nGEMINI_MODEL=\"backend model\"\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "shell-model")

    loaded = load_local_env(root)

    assert loaded == (backend / ".env", root / ".env")
    # The more specific backend file wins over the root file, while an explicit
    # process value is never replaced.
    assert os.environ["GEMINI_API_KEY"] == "backend-secret"
    assert os.environ["GEMINI_MODEL"] == "shell-model"
    # load_local_env intentionally uses os.environ directly; remove the newly
    # loaded secret so this test cannot affect later provider tests.
    os.environ.pop("GEMINI_API_KEY", None)
