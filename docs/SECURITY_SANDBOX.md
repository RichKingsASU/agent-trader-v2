## Security sandbox: Firecracker strategy execution

This repository uses a **microVM sandbox** to execute tenant-provided Python strategies.

### Goals (non-negotiable)

- **No strategy code runs directly on the host runtime.**
- **Strict I/O interface**: strategies only receive **market event JSON** and can only emit **order intent JSON**.
- **No direct secrets access**: strategies **never receive Firebase / Firestore credentials** (or other platform secrets).
- **Tenant isolation**: a strategy cannot access other tenants’ code/data or the host filesystem.

### Architecture (high level)

- **Host (platform)**
  - Receives strategy uploads (Python files).
  - Packages code into a **bundle** (immutable `tar.gz`) without importing it.
  - Launches a Firecracker **microVM** with:
    - read-only root filesystem (guest runtime)
    - a read-only “strategy drive” containing only the bundle
    - **no network interfaces** by default
  - Streams market events to the guest and receives order intents back.
  - Validates order intents and forwards them to broker/risk services.

- **Guest (sandbox)**
  - Unpacks the bundle into a guest-local directory.
  - Imports only the user entrypoint.
  - Listens on **vsock** for NDJSON messages.
  - Emits only `order_intent` messages (plus optional `log` messages).

### Strategy protocol (strict interface)

All communication is **NDJSON** (newline-delimited JSON), UTF-8.

- **Inbound (host → guest)**:
  - `market_event`:
    - required: `protocol`, `type`, `event_id`, `ts`, `symbol`, `source`, `payload`
  - `shutdown`

- **Outbound (guest → host)**:
  - `order_intent`:
    - required: `protocol`, `type`, `intent_id`, `event_id`, `ts`, `symbol`, `side`, `qty`, `order_type`
  - `log` (optional)

Reference implementation: `backend/strategy_runner/protocol.py`.

### What a strategy can do

- **Allowed**
  - Read the inbound `market_event` JSON.
  - Maintain in-memory state (within VM lifetime).
  - Emit `order_intent` JSON messages.

- **Not allowed / not available**
  - **No host filesystem access** (only guest rootfs + attached strategy drive).
  - **No other tenants** (separate microVMs, separate disks, separate processes).
  - **No platform credentials** (Firebase, Firestore, Alpaca keys, etc.).
  - **No network** by default (no NICs; no metadata server access).

### Isolation boundaries

- **CPU/memory isolation**: each strategy runs in its own Firecracker microVM process boundary.
- **Filesystem isolation**:
  - rootfs is mounted read-only
  - strategy bundle is delivered via a dedicated read-only block device
  - no host path mounts into the guest
- **Network isolation**:
  - default: no network devices
  - if enabled in the future, use explicit allow-list egress and per-tenant policy
- **Secret isolation**:
  - no secrets are mounted into the guest
  - the host translates intents → broker actions using its own credentials

### Threat model (selected)

- **Tenant code attempts to exfiltrate secrets**
  - mitigations: no secrets in guest; no network by default; no metadata endpoint

- **Tenant code attempts host filesystem reads**
  - mitigations: no host mounts; microVM boundary; read-only guest images

- **Tenant code attempts cross-tenant reads/writes**
  - mitigations: one microVM per tenant execution; distinct block devices; no shared IPC

- **Denial of service (CPU/mem)**
  - mitigations: microVM resource limits (vCPU/memory); host-side timeouts; kill/restart VM

- **Kernel / hypervisor escape**
  - mitigations: Firecracker’s minimal device model; keep kernel + Firecracker patched; enable seccomp filters; run with least privilege

### Local validation (hello strategy)

This repo ships a “hello strategy” and harness:

- **Example strategy**: `backend/strategy_runner/examples/hello_strategy/strategy.py`
- **Simulated events**: `backend/strategy_runner/examples/hello_strategy/events.ndjson`
- **Harness**: `backend/strategy_runner/harness.py`

To run locally you must provide Firecracker assets:

- `FIRECRACKER_BIN`: path to `firecracker`
- `FC_KERNEL_IMAGE`: path to a Linux kernel image compatible with Firecracker
- `FC_ROOTFS_IMAGE`: path to a guest rootfs that starts `guest_runner.py` and mounts the strategy drive at `/mnt/strategy`

### Notes / current limitations (scaffolding)

- The host runner builds a strategy ext4 drive image via `mke2fs -d` (requires `e2fsprogs`).
- The guest rootfs must include Python and a service that executes `backend/strategy_runner/guest/guest_runner.py`.
  - The guest runner expects the bundle at `/mnt/strategy/bundle.tar.gz` by default.

