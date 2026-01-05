from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


class BundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class StrategyBundle:
    """
    A bundle is an immutable tar.gz that can be injected into a microVM.

    The host MUST NOT import or execute user code; it only packages files.
    The guest runner will unpack this archive and import the user entrypoint.
    """

    bundle_path: Path
    sha256: str
    manifest: Dict[str, object]


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_relpath(base: Path, p: Path) -> str:
    rel = p.relative_to(base).as_posix()
    if rel.startswith("/") or rel.startswith("../") or "/../" in rel:
        raise BundleError("unsafe path in bundle")
    return rel


def create_strategy_bundle(
    *,
    strategy_source: Union[str, Path],
    entrypoint: str = "user_strategy.py",
    strategy_id: str = "strategy",
    out_dir: Optional[Union[str, Path]] = None,
) -> StrategyBundle:
    """
    Create a tar.gz bundle containing user strategy code + a manifest.

    strategy_source may be:
    - a single .py file
    - a directory containing python files

    The bundle layout is:
    - manifest.json
    - strategy/<user files...>  (entrypoint must exist under strategy/)
    """

    src = Path(strategy_source).resolve()
    if not src.exists():
        raise BundleError(f"strategy_source not found: {src}")

    if out_dir is None:
        out_dir_path = Path(tempfile.mkdtemp(prefix="strategy_bundle_"))
    else:
        out_dir_path = Path(out_dir).resolve()
        out_dir_path.mkdir(parents=True, exist_ok=True)

    bundle_path = out_dir_path / f"{strategy_id}.tar.gz"

    # Collect files without importing them.
    files: List[Tuple[Path, str]] = []
    if src.is_file():
        if src.suffix != ".py":
            raise BundleError("strategy_source file must be .py")
        files.append((src, f"strategy/{entrypoint}"))
    else:
        # Directory: include *.py and typical metadata files (optional)
        for p in sorted(src.rglob("*")):
            if p.is_dir():
                continue
            if p.name.startswith("."):
                continue
            if p.suffix in (".py", ".txt", ".md", ".json", ".yaml", ".yml"):
                rel = _safe_relpath(src, p)
                files.append((p, f"strategy/{rel}"))

        # Ensure entrypoint exists
        ep = src / entrypoint
        if not ep.exists():
            raise BundleError(f"entrypoint not found in directory: {ep}")

    manifest: Dict[str, object] = {
        "schema": "agenttrader.strategy_bundle.v1",
        "strategy_id": strategy_id,
        "entrypoint": entrypoint,
        "files": [dst for _, dst in files],
    }

    with tarfile.open(bundle_path, "w:gz") as tf:
        # Add manifest first for fast validation in guest.
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        info.mode = 0o444
        tf.addfile(info, fileobj=_BytesReader(manifest_bytes))

        for src_path, dst_name in files:
            ti = tf.gettarinfo(str(src_path), arcname=dst_name)
            # Always reduce permissions inside the bundle.
            ti.mode = 0o444
            with src_path.open("rb") as f:
                tf.addfile(ti, fileobj=f)

    sha256 = _sha256_file(bundle_path)
    return StrategyBundle(bundle_path=bundle_path, sha256=sha256, manifest=manifest)


class _BytesReader:
    def __init__(self, b: bytes):
        self._b = b
        self._i = 0

    def read(self, n: int = -1) -> bytes:
        if n == 0:
            return b""
        if n < 0:
            out = self._b[self._i :]
            self._i = len(self._b)
            return out
        out = self._b[self._i : self._i + n]
        self._i += len(out)
        return out

