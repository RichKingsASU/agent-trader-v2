import tarfile
from pathlib import Path

from backend.strategy_runner.bundle import BundleError, create_strategy_bundle


def test_create_strategy_bundle_from_file(tmp_path: Path):
    src = tmp_path / "my_strategy.py"
    src.write_text("def on_market_event(event):\n    return []\n", encoding="utf-8")

    b = create_strategy_bundle(strategy_source=src, strategy_id="t1", entrypoint="user_strategy.py", out_dir=tmp_path)
    assert b.bundle_path.exists()
    assert len(b.sha256) == 64
    assert b.manifest["entrypoint"] == "user_strategy.py"

    with tarfile.open(b.bundle_path, "r:gz") as tf:
        names = set(tf.getnames())
        assert "manifest.json" in names
        assert "strategy/user_strategy.py" in names


def test_create_strategy_bundle_from_dir_requires_entrypoint(tmp_path: Path):
    d = tmp_path / "dir"
    d.mkdir()
    (d / "other.py").write_text("x=1\n", encoding="utf-8")
    try:
        create_strategy_bundle(strategy_source=d, strategy_id="t1", entrypoint="user_strategy.py", out_dir=tmp_path)
        assert False, "expected BundleError"
    except BundleError:
        pass

