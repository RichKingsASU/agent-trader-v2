import os
from pathlib import Path

import pytest

from backend.strategy_runner.protocol import loads_ndjson
from backend.strategy_runner.runner import FirecrackerAssets, StrategySandboxRunner


@pytest.mark.skipif(
    not (os.getenv("FIRECRACKER_BIN") and os.getenv("FC_KERNEL_IMAGE") and os.getenv("FC_ROOTFS_IMAGE")),
    reason="requires local Firecracker assets (FIRECRACKER_BIN, FC_KERNEL_IMAGE, FC_ROOTFS_IMAGE)",
)
def test_firecracker_hello_strategy_smoke():
    firecracker_bin = os.getenv("FIRECRACKER_BIN")
    kernel_image = os.getenv("FC_KERNEL_IMAGE")
    rootfs_image = os.getenv("FC_ROOTFS_IMAGE")
    assert firecracker_bin and kernel_image and rootfs_image
    assets = FirecrackerAssets(
        firecracker_bin=Path(firecracker_bin).resolve(),
        kernel_image=Path(kernel_image).resolve(),
        rootfs_image=Path(rootfs_image).resolve(),
    )
    runner = StrategySandboxRunner(assets=assets)

    strategy_dir = Path("backend/strategy_runner/examples/hello_strategy").resolve()
    events_path = strategy_dir / "events.ndjson"
    events = loads_ndjson(events_path.read_bytes())

    intents = runner.run(strategy_source=strategy_dir, events=events, strategy_id="hello")
    # At least one intent expected for price >= 100
    assert any(i.get("type") == "order_intent" for i in intents)

