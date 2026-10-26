"""The load test refuses to run against anything but this machine."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "load_test.py"


def _load():
    spec = importlib.util.spec_from_file_location("load_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_local_addresses_are_accepted():
    lt = _load()
    assert lt.is_local("http://localhost:8000") and lt.is_local("http://127.0.0.1:8000")
    assert lt.is_local("mongodb://user:pw@127.0.0.1:27017/db?authSource=db")
    assert not lt.is_local("https://antiproxypr.duckdns.org")
    assert not lt.is_local("mongodb+srv://cluster0.example.mongodb.net/db")


def test_a_remote_target_is_refused_before_anything_runs(capsys):
    lt = _load()
    assert lt.main(["--base-url", "https://antiproxypr.duckdns.org"]) == 2
    assert "only against this machine" in capsys.readouterr().out


def test_percentiles():
    lt = _load()
    assert lt.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
    assert lt.percentile([], 0.95) == 0.0
