## Structured logging (JSON) + correlation IDs

Backend services emit **one JSON object per log line** to stdout via stdlib `logging`, with a consistent core schema and request correlation via `X-Request-ID`.

### Standard fields (always present)

- **`service`**: Logical service name (ex: `execution-engine`)
- **`env`**: Environment (from `ENVIRONMENT`/`ENV`/`APP_ENV`)
- **`version`**: Deploy/version identifier (from `AGENT_VERSION`/`APP_VERSION`/`VERSION`/`IMAGE_TAG`/`K_REVISION`)
- **`sha`**: Git SHA (from `GIT_SHA`/CI vars)
- **`request_id`**: Request ID (from `X-Request-ID`, generated if missing)
- **`correlation_id`**: Alias of `request_id` for internal tracing consistency
- **`event_type`**: Stable event name (ex: `http.request`, `intent.start`)
- **`severity`**: Log severity (Cloud Logging-compatible)

Other useful fields commonly included:
- **`timestamp`**, **`message`**, **`logger`**
- HTTP logs: **`method`**, **`path`**, **`status_code`**, **`duration_ms`**

### HTTP request ID propagation

For FastAPI services we install middleware that:
- Reads incoming **`X-Request-ID`** (preferred) or `X-Correlation-Id` (fallback)
- Generates a new ID if missing
- Binds it for the lifetime of the request (so application logs automatically include it)
- Echoes it back on the response as **`X-Request-ID`** (and `X-Correlation-Id` for back-compat)
- Emits a single log event per request: `event_type="http.request"`

### How to use in services

- **Initialize JSON logging once at import/startup**
  - `backend/common/logging.py:init_structured_logging(...)`
- **Install FastAPI middleware**
  - `backend/common/logging.py:install_fastapi_request_id_middleware(app, ...)`

### Query examples (local files)

Assuming you have a log file containing JSON lines:

- **All HTTP requests**

```bash
jq -c 'select(.event_type=="http.request")' service.log
```

- **5xx requests**

```bash
jq -c 'select(.event_type=="http.request" and (.status_code//0) >= 500)' service.log
```

- **Trace a single request across services**

```bash
jq -c 'select(.request_id=="<REQUEST_ID>")' service.log
```

- **Quick grep without parsing**

```bash
rg '"request_id":"<REQUEST_ID>"' service.log
```

### Query examples (Google Cloud Logging)

Note: queries differ slightly based on runtime (`cloud_run_revision` vs `k8s_container`).

- **All logs for a service**

```
jsonPayload.service="execution-engine"
```

- **HTTP requests for a service**

```
jsonPayload.service="execution-engine"
jsonPayload.event_type="http.request"
```

- **Trace a single request**

```
jsonPayload.request_id="<REQUEST_ID>"
```

- **Errors**

```
jsonPayload.service="execution-engine"
severity>=ERROR
```

