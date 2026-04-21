"""Tests for the curated smoke-test runner."""

from __future__ import annotations

from argparse import Namespace

import pytest

from optiland_gui import smoke_runner


def test_smoke_runner_lists_suite(capsys, monkeypatch):
    monkeypatch.setattr(
        smoke_runner,
        "_parse_args",
        lambda: Namespace(list=True, pytest_args=[]),
    )

    smoke_runner.main()

    captured = capsys.readouterr()
    assert "Optiland smoke suite:" in captured.out
    for path in smoke_runner.SMOKE_TESTS:
        assert path in captured.out


def test_smoke_runner_invokes_pytest(monkeypatch):
    called = {}

    def fake_call(command, cwd=None):  # noqa: ANN001
        called["command"] = command
        called["cwd"] = cwd
        return 0

    monkeypatch.setattr(
        smoke_runner,
        "_parse_args",
        lambda: Namespace(list=False, pytest_args=["-q"]),
    )
    monkeypatch.setattr(smoke_runner.subprocess, "call", fake_call)

    with pytest.raises(SystemExit) as exc_info:
        smoke_runner.main()

    assert exc_info.value.code == 0
    assert called["command"][:3] == [smoke_runner.sys.executable, "-m", "pytest"]
    assert called["command"][3:-1] == smoke_runner.SMOKE_TESTS
    assert called["command"][-1] == "-q"
    assert called["cwd"] == smoke_runner._project_root()
