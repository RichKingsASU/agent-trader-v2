from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .bundle import StrategyBundle, create_strategy_bundle
from .firecracker import FirecrackerConfig, FirecrackerMicroVM
from .protocol import PROTOCOL_VERSION, parse_order_intent


class StrategyRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirecrackerAssets:
    firecracker_bin: Path
    kernel_image: Path
    rootfs_image: Path


def make_strategy_drive_image(
    *,
    bundle: StrategyBundle,
    out_dir: Optional[Union[str, Path]] = None,
    size_mib: int = 64,
) -> Path:
    """
    Create a small ext4 disk image containing:
    - /bundle.tar.gz  (the strategy bundle)

    This image is intended to be attached to the microVM as a read-only drive
    (e.g., /dev/vdb) and mounted by the guest init/service at /mnt/strategy.
    """
    if out_dir is None:
        out_dir_path = Path(tempfile.mkdtemp(prefix="strategy_drive_"))
    else:
        out_dir_path = Path(out_dir).resolve()
        out_dir_path.mkdir(parents=True, exist_ok=True)

    staging = out_dir_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "bundle.tar.gz").write_bytes(bundle.bundle_path.read_bytes())

    img = out_dir_path / "strategy.ext4"

    # Populate via mke2fs -d (requires e2fsprogs).
    # Example: mke2fs -t ext4 -F -d staging strategy.ext4 64M
    cmd = [
        "mke2fs",
        "-t",
        "ext4",
        "-F",
        "-d",
        str(staging),
        str(img),
        f"{size_mib}M",
    ]
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise StrategyRunnerError(
            "mke2fs not found (install e2fsprogs) to build a strategy drive image"
        ) from e
    except subprocess.CalledProcessError as e:
        raise StrategyRunnerError(f"failed to build ext4 strategy image: {e}") from e

    return img


def _read_ndjson(sock_f) -> Iterable[Dict[str, Any]]:
    for raw in sock_f:
        raw = raw.strip()
        if not raw:
            continue
        yield json.loads(raw.decode("utf-8"))


def _send_ndjson(sock_f, objs: Iterable[Dict[str, Any]]) -> None:
    for o in objs:
        sock_f.write(json.dumps(o, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        sock_f.write(b"\n")
    sock_f.flush()


def _connect_vsock(guest_cid: int, port: int, timeout_s: float = 5.0) -> socket.socket:
    if not hasattr(socket, "AF_VSOCK"):
        raise StrategyRunnerError("host kernel/python missing AF_VSOCK support")
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)  # type: ignore[attr-defined]
    s.settimeout(1.0)
    start = time.time()
    last_err: Optional[Exception] = None
    while time.time() - start < timeout_s:
        try:
            s.connect((guest_cid, port))
            s.settimeout(None)
            return s
        except Exception as e:
            last_err = e
            time.sleep(0.05)
    try:
        s.close()
    except Exception:
        pass
    raise StrategyRunnerError(f"failed to connect vsock to guest cid={guest_cid} port={port}: {last_err}")


@dataclass
class StrategySandboxRunner:
    """
    Host-side orchestrator:
    - package user strategy into a bundle
    - inject it into a microVM via an attached read-only drive image
    - stream market events in; collect order intents out
    """

    assets: FirecrackerAssets
    guest_cid: int = 3
    vsock_port: int = 5005

    def run(
        self,
        *,
        strategy_source: Union[str, Path],
        events: Sequence[Dict[str, Any]],
        strategy_id: str = "strategy",
    ) -> List[Dict[str, Any]]:
        bundle = create_strategy_bundle(strategy_source=strategy_source, strategy_id=strategy_id)
        drive_img = make_strategy_drive_image(bundle=bundle)

        cfg = FirecrackerConfig(
            firecracker_bin=self.assets.firecracker_bin,
            kernel_image=self.assets.kernel_image,
            rootfs_image=self.assets.rootfs_image,
            guest_cid=self.guest_cid,
            vsock_port=self.vsock_port,
            strategy_drive_image=drive_img,
        )

        intents: List[Dict[str, Any]] = []
        with FirecrackerMicroVM(cfg) as vm:
            # guest is expected to have started its runner and listen on vsock_port
            s = _connect_vsock(self.guest_cid, self.vsock_port, timeout_s=10.0)
            with s:
                rf = s.makefile("rb", buffering=0)
                wf = s.makefile("wb", buffering=0)

                # Optional: read initial logs
                start_deadline = time.time() + 2.0
                while time.time() < start_deadline:
                    s.settimeout(0.1)
                    try:
                        line = rf.readline()
                    except Exception:
                        break
                    if not line:
                        break
                    msg = json.loads(line.decode("utf-8"))
                    # ignore logs
                    if msg.get("type") != "log":
                        break
                s.settimeout(None)

                _send_ndjson(wf, events)
                _send_ndjson(wf, [{"protocol": PROTOCOL_VERSION, "type": "shutdown"}])

                for msg in _read_ndjson(rf):
                    if msg.get("type") == "order_intent":
                        # validate shape
                        _ = parse_order_intent(msg)
                        intents.append(msg)
                    if msg.get("type") == "log" and msg.get("level") == "error":
                        # keep log errors, but don't fail automatically in scaffolding
                        pass

        return intents

