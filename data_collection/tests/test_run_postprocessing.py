"""Tests for the subprocess isolation helper."""

import pytest

from run_postprocessing import run_isolated


def double(x):
    return x * 2


def explode():
    raise ValueError("boom")


def test_run_isolated_returns_the_result():
    assert run_isolated(double, 21) == 42


def test_run_isolated_raises_when_the_child_fails():
    with pytest.raises(RuntimeError, match="explode failed in subprocess"):
        run_isolated(explode)
