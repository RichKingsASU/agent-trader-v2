# Hardening Notes for `cloudrun_ingestor`

This document explains the reliability improvements made to the `cloudrun_ingestor` service to make it production-ready.

### 1. SIGTERM Handling for Graceful Shutdown

-   **Why it Matters:** Cloud Run sends a `SIGTERM` signal to a container to ask it to shut down, providing a 10-second grace period. The original script had no way to catch this signal. This meant the process could be killed abruptly in the middle of a `time.sleep()` or, more critically, during the retry backoff period of a failing Pub/Sub publish. This leads to data loss and prevents the service from logging its own shutdown.
-   **The Change:** A signal handler was added to catch `SIGTERM` and `SIGINT`. This handler sets a global `SHUTDOWN_FLAG` and **chains any previous handlers** (so Gunicorn/framework shutdown still behaves correctly). Any waits use `SHUTDOWN_FLAG.wait(timeout=...)` (a shared event) so shutdown can interrupt the wait and exit quickly.

### 2. Runtime Stability with Gunicorn

-   **Why it Matters:** The original service was started with `python main.py`, which uses Python's built-in Flask development server. This server is not designed for production; it's single-threaded, can't handle multiple requests (even health checks), and is not resilient. A production-grade WSGI server is required for stability and proper process management.
-   **The Change:** `gunicorn` was added as a dependency. The `Dockerfile` `CMD` was changed to launch the application via `gunicorn`. This provides a stable, battle-tested process manager to run the service indefinitely. We use a single worker (`--workers 1`) and a single thread (`--threads 1`) because this is a single-threaded background job, not a web server handling concurrent user requests. `--timeout 0` disables Gunicorn’s *request/worker heartbeat* timeout so it won’t kill the worker during long idle/wait intervals (common for background loops). Shutdown is still bounded by Cloud Run’s SIGTERM grace period, and we keep Gunicorn’s `graceful_timeout` aligned to ~10s.

### 3. Structured (JSON) Logging

-   **Why it Matters:** The original logs were unstructured strings. In a production system, this is a major operational deficiency. String logs are difficult to query reliably in Cloud Logging (e.g., "show me all logs where `iteration_id` is X and `severity` is `ERROR`"). This slows down debugging and makes it nearly impossible to create accurate, log-based alerts.
-   **The Change:** The `google-cloud-logging` library was installed and configured. This library automatically hijacks Python's standard `logging` module to output logs as structured JSON objects. We now add custom, queryable fields (`service`, `env`, `iteration_id`, etc.) to the log output using the `extra` parameter. This makes logs machine-readable, dramatically improving observability and our ability to debug and alert on specific conditions.

### 4. Local shutdown smoke test

To prove shutdown completes within Cloud Run’s ~10s SIGTERM grace period:

```bash
python -m cloudrun_ingestor.shutdown_smoke
# in another shell: kill -TERM <pid>
```
