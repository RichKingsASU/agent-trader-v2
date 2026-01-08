from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from backend.common.shutdown import SHUTDOWN_EVENT, install_signal_handlers_once, wait_or_shutdown
from .firecracker_api import UnixHTTPClient


class FirecrackerError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirecrackerArtifacts:
    api_sock: Path
    log_path: Path
    metrics_path: Path
    vm_dir: Path


@dataclass(frozen=True)
class FirecrackerConfig:
    firecracker_bin: Path
    kernel_image: Path
    rootfs_image: Path
    guest_cid: int = 3
    vsock_port: int = 5005
    vcpu_count: int = 1
    mem_mib: int = 256
    rootfs_is_read_only: bool = True
    # Optional extra block device used to deliver the strategy bundle.
    strategy_drive_image: Optional[Path] = None


class FirecrackerMicroVM:
    def __init__(self, cfg: FirecrackerConfig):
        self.cfg = cfg
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._artifacts: Optional[FirecrackerArtifacts] = None

    @property
    def artifacts(self) -> FirecrackerArtifacts:
        if self._artifacts is None:
            raise FirecrackerError("microVM not started")
        return self._artifacts

    def start(self) -> None:
        if self._proc is not None:
            raise FirecrackerError("microVM already started")

        for p in (self.cfg.firecracker_bin, self.cfg.kernel_image, self.cfg.rootfs_image):
            if not p.exists():
                raise FirecrackerError(f"missing required file: {p}")

        if shutil.which(str(self.cfg.firecracker_bin)) is None and not os.access(self.cfg.firecracker_bin, os.X_OK):
            raise FirecrackerError(f"firecracker binary not executable: {self.cfg.firecracker_bin}")

        vm_dir = Path(tempfile.mkdtemp(prefix="agenttrader_fc_"))
        api_sock = vm_dir / "firecracker.socket"
        log_path = vm_dir / "firecracker.log"
        metrics_path = vm_dir / "firecracker.metrics"

        self._artifacts = FirecrackerArtifacts(
            api_sock=api_sock,
            log_path=log_path,
            metrics_path=metrics_path,
            vm_dir=vm_dir,
        )

        cmd = [
            str(self.cfg.firecracker_bin),
            "--api-sock",
            str(api_sock),
            "--log-path",
            str(log_path),
            "--metrics-path",
            str(metrics_path),
            "--level",
            "Info",
        ]
        # NOTE: firecracker will create the socket when ready to accept API calls.
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        self._wait_for_api_socket(api_sock, timeout_s=2.0)
        self._configure()

    def _wait_for_api_socket(self, sock: Path, timeout_s: float) -> None:
        # Best-effort: allow SIGTERM/SIGINT to interrupt waits.
        install_signal_handlers_once()
        start = time.time()
        while time.time() - start < timeout_s:
            if sock.exists():
                return
            if SHUTDOWN_EVENT.is_set():
                raise FirecrackerError("shutdown requested while waiting for API socket")
            wait_or_shutdown(0.02)
        raise FirecrackerError(f"firecracker API socket not created: {sock}")

    def _api(self) -> UnixHTTPClient:
        return UnixHTTPClient(str(self.artifacts.api_sock))

    def _put(self, path: str, payload: Dict[str, Any]) -> None:
        r = self._api().request("PUT", path, payload)
        if r.status not in (200, 204):
            raise FirecrackerError(f"firecracker API PUT {path} failed: {r.status} {r.body!r}")

    def _configure(self) -> None:
        # 1) machine config
        self._put(
            "/machine-config",
            {
                "vcpu_count": self.cfg.vcpu_count,
                "mem_size_mib": self.cfg.mem_mib,
                "smt": False,
            },
        )

        # 2) boot source
        boot_args = " ".join(
            [
                "console=ttyS0",
                "reboot=k",
                "panic=1",
                "pci=off",
                # guest runner is expected to be started by rootfs init/systemd
            ]
        )
        self._put(
            "/boot-source",
            {
                "kernel_image_path": str(self.cfg.kernel_image),
                "boot_args": boot_args,
            },
        )

        # 3) rootfs
        self._put(
            "/drives/rootfs",
            {
                "drive_id": "rootfs",
                "path_on_host": str(self.cfg.rootfs_image),
                "is_root_device": True,
                "is_read_only": self.cfg.rootfs_is_read_only,
            },
        )

        # 4) strategy drive (optional): guest should mount and read bundle.tar.gz
        if self.cfg.strategy_drive_image is not None:
            self._put(
                "/drives/strategy",
                {
                    "drive_id": "strategy",
                    "path_on_host": str(self.cfg.strategy_drive_image),
                    "is_root_device": False,
                    "is_read_only": True,
                },
            )

        # 5) vsock device for host<->guest communication (no network required)
        # Firecracker expects "uds_path" (host-side) for the vsock backend.
        vsock_uds = str(self.artifacts.vm_dir / "vsock.sock")
        self._put(
            "/vsock",
            {
                "guest_cid": self.cfg.guest_cid,
                "uds_path": vsock_uds,
            },
        )

        # 6) start instance
        self._put("/actions", {"action_type": "InstanceStart"})

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2.0)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        finally:
            self._proc = None

    def cleanup(self) -> None:
        if self._artifacts is None:
            return
        try:
            shutil.rmtree(self._artifacts.vm_dir, ignore_errors=True)
        finally:
            self._artifacts = None

    def __enter__(self) -> "FirecrackerMicroVM":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
        self.cleanup()

