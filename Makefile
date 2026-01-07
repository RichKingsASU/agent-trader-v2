.PHONY: report report-skip-health
.PHONY: day1-dry-run
.PHONY: ci-validate

# -----------------------------------------------------------------------------
# AgentTrader v2 — “Trading Floor” one-command workflow
#
# Safety rules:
# - This Makefile does NOT enable trading execution.
# - No secrets are embedded.
# - Targets degrade gracefully when tools/clusters are unavailable.
# -----------------------------------------------------------------------------

# Overridable configuration (safe defaults)
NAMESPACE ?= default
K8S_DIR ?= k8s
PROJECT_ID ?= 
REGION ?= 
CONTEXT ?= 
MISSION_CONTROL_URL ?= http://agenttrader-mission-control

PY ?= python3

.PHONY: lock lock-check

# -----------------------------------------------------------------------------
# Dependency locking (backend)
#
# We intentionally lock backend services separately from Firebase Functions:
# they are deployed/built independently and may carry conflicting pins.
# -----------------------------------------------------------------------------

PIP_VERSION ?= 24.3.1
PIP_TOOLS_VERSION ?= 7.4.1

lock: ## Generate backend *.lock files from requirements.txt
	@echo "== lock (backend) =="
	@$(PY) -m pip install --upgrade --user "pip==$(PIP_VERSION)" "pip-tools==$(PIP_TOOLS_VERSION)"
	@$(PY) -m piptools compile --quiet --no-strip-extras --output-file backend/requirements.lock backend/requirements.txt
	@$(PY) -m piptools compile --quiet --no-strip-extras --output-file backend/strategy_service/requirements.lock backend/strategy_service/requirements.txt
	@$(PY) -m piptools compile --quiet --no-strip-extras --output-file backend/risk_service/requirements.lock backend/risk_service/requirements.txt
	@$(PY) -m piptools compile --quiet --no-strip-extras --output-file backend/mission_control/requirements.lock backend/mission_control/requirements.txt
	@$(PY) -m piptools compile --quiet --no-strip-extras --output-file backend/execution_agent/requirements.lock backend/execution_agent/requirements.txt
	@$(PY) -m piptools compile --quiet --no-strip-extras --output-file backend/strategy_engine/requirements.lock backend/strategy_engine/requirements.txt
	@echo "OK: updated backend/*.lock files"

lock-check: ## Fail if backend *.lock files are out of date
	@echo "== lock-check (backend) =="
	@$(PY) -m pip install --upgrade --user "pip==$(PIP_VERSION)" "pip-tools==$(PIP_TOOLS_VERSION)"
	@tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; \
		set -eu; \
		$(PY) -m piptools compile --quiet --no-strip-extras --output-file "$$tmp/backend.requirements.lock" backend/requirements.txt; \
		sed '/^#    pip-compile /d' backend/requirements.lock > "$$tmp/backend.requirements.norm.lock"; \
		sed '/^#    pip-compile /d' "$$tmp/backend.requirements.lock" > "$$tmp/backend.requirements.norm.tmp.lock"; \
		diff -u "$$tmp/backend.requirements.norm.lock" "$$tmp/backend.requirements.norm.tmp.lock"; \
		$(PY) -m piptools compile --quiet --no-strip-extras --output-file "$$tmp/strategy_service.requirements.lock" backend/strategy_service/requirements.txt; \
		sed '/^#    pip-compile /d' backend/strategy_service/requirements.lock > "$$tmp/strategy_service.requirements.norm.lock"; \
		sed '/^#    pip-compile /d' "$$tmp/strategy_service.requirements.lock" > "$$tmp/strategy_service.requirements.norm.tmp.lock"; \
		diff -u "$$tmp/strategy_service.requirements.norm.lock" "$$tmp/strategy_service.requirements.norm.tmp.lock"; \
		$(PY) -m piptools compile --quiet --no-strip-extras --output-file "$$tmp/risk_service.requirements.lock" backend/risk_service/requirements.txt; \
		sed '/^#    pip-compile /d' backend/risk_service/requirements.lock > "$$tmp/risk_service.requirements.norm.lock"; \
		sed '/^#    pip-compile /d' "$$tmp/risk_service.requirements.lock" > "$$tmp/risk_service.requirements.norm.tmp.lock"; \
		diff -u "$$tmp/risk_service.requirements.norm.lock" "$$tmp/risk_service.requirements.norm.tmp.lock"; \
		$(PY) -m piptools compile --quiet --no-strip-extras --output-file "$$tmp/mission_control.requirements.lock" backend/mission_control/requirements.txt; \
		sed '/^#    pip-compile /d' backend/mission_control/requirements.lock > "$$tmp/mission_control.requirements.norm.lock"; \
		sed '/^#    pip-compile /d' "$$tmp/mission_control.requirements.lock" > "$$tmp/mission_control.requirements.norm.tmp.lock"; \
		diff -u "$$tmp/mission_control.requirements.norm.lock" "$$tmp/mission_control.requirements.norm.tmp.lock"; \
		$(PY) -m piptools compile --quiet --no-strip-extras --output-file "$$tmp/execution_agent.requirements.lock" backend/execution_agent/requirements.txt; \
		sed '/^#    pip-compile /d' backend/execution_agent/requirements.lock > "$$tmp/execution_agent.requirements.norm.lock"; \
		sed '/^#    pip-compile /d' "$$tmp/execution_agent.requirements.lock" > "$$tmp/execution_agent.requirements.norm.tmp.lock"; \
		diff -u "$$tmp/execution_agent.requirements.norm.lock" "$$tmp/execution_agent.requirements.norm.tmp.lock"; \
		$(PY) -m piptools compile --quiet --no-strip-extras --output-file "$$tmp/strategy_engine.requirements.lock" backend/strategy_engine/requirements.txt; \
		sed '/^#    pip-compile /d' backend/strategy_engine/requirements.lock > "$$tmp/strategy_engine.requirements.norm.lock"; \
		sed '/^#    pip-compile /d' "$$tmp/strategy_engine.requirements.lock" > "$$tmp/strategy_engine.requirements.norm.tmp.lock"; \
		diff -u "$$tmp/strategy_engine.requirements.norm.lock" "$$tmp/strategy_engine.requirements.norm.tmp.lock"; \
		echo "OK: lock files are in sync"

.PHONY: help fmt lint smoke-check test build frontend-build deploy guard report readiness status git-status logs scale port-forward clean dev

help: ## Show available targets and usage
	@echo "AgentTrader v2 — Trading Floor Makefile"
	@echo ""
	@echo "Usage:"
	@echo "  make <target> [VAR=value ...]"
	@echo ""
	@echo "Common vars (overridable):"
	@echo "  NAMESPACE=$(NAMESPACE)"
	@echo "  K8S_DIR=$(K8S_DIR)"
	@echo "  PROJECT_ID=$(if $(PROJECT_ID),$(PROJECT_ID),<empty>)"
	@echo "  REGION=$(if $(REGION),$(REGION),<empty>)"
	@echo "  CONTEXT=$(if $(CONTEXT),$(CONTEXT),<empty>)"
	@echo "  MISSION_CONTROL_URL=$(MISSION_CONTROL_URL)"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort
	@echo ""
	@echo "Examples:"
	@echo "  make guard && make deploy && make report"
	@echo "  make readiness NAMESPACE=trading-floor"
	@echo "  make logs AGENT=strategy-engine"

dev: ## Start local development environment (backend + frontend)
	@echo "Running local development environment..."
	@if [ ! -f ./scripts/dev_all.sh ]; then echo "Error: ./scripts/dev_all.sh not found! Cannot start dev environment."; exit 1; fi
	@./scripts/dev_all.sh

fmt: ## Best-effort formatting (python + yaml)
	@echo "== fmt (best-effort) =="
	@if command -v ruff >/dev/null 2>&1; then \
		echo "[python] ruff format ."; ruff format .; \
	elif command -v black >/dev/null 2>&1; then \
		echo "[python] black ."; black .; \
	else \
		echo "INFO: python formatter not found (install ruff or black)"; \
	fi
	@if command -v isort >/dev/null 2>&1; then \
		echo "[python] isort ."; isort .; \
	else \
		echo "INFO: isort not found (optional)"; \
	fi
	@if command -v yamlfmt >/dev/null 2>&1; then \
		echo "[yaml] yamlfmt -w"; \
		for d in "$(K8S_DIR)" config configs .github infra k8s; do \
			[[ -d "$$d" ]] && yamlfmt -w "$$d" || true; \
		done; \
	else \
		echo "INFO: yamlfmt not found (optional)"; \
	fi

lint: smoke-check ## Best-effort lint checks (includes import smoke check)
	@echo "== lint (best-effort) =="
	@if command -v ruff >/dev/null 2>&1; then \
		echo "[python] ruff check ."; ruff check .; \
	else \
		echo "INFO: ruff not found (install ruff for faster linting)"; \
	fi
	@if command -v black >/dev/null 2>&1; then \
		echo "[python] black --check ."; black --check .; \
	else \
		echo "INFO: black not found (optional)"; \
	fi
	@if command -v yamllint >/dev/null 2>&1; then \
		echo "[yaml] yamllint"; yamllint -s "$(K8S_DIR)" configs config .github 2>/dev/null || yamllint -s .; \
	else \
		echo "INFO: yamllint not found (optional)"; \
	fi

smoke-check: ## Run Python import smoke tests
	@echo "== smoke-check =="
	@if [ ! -f ./scripts/smoke_check_imports.py ]; then echo "ERROR: missing ./scripts/smoke_check_imports.py"; exit 1; fi
	@"$(PY)" ./scripts/smoke_check_imports.py

ci-validate: ## Validate CI layout (cloudbuild.yaml references)
	@echo "== ci-validate =="
	@bash ./scripts/validate_ci_layout.sh

test: ## Run python tests if present
	@echo "== test =="
	@if [[ -d "tests" ]]; then \
		if "$(PY)" -m pytest -q; then \
			echo "OK: tests passed"; \
		else \
			echo "FAIL: pytest failed (ensure dependencies installed)"; \
			exit 1; \
		fi \
	else \
		echo "INFO: no ./tests directory found (skipping)"; \
	fi

build: ## Build images locally if possible; else print instructions
	@echo "== build =="
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "INFO: docker not found. To build images locally:"; \
		echo "  docker build -f infra/Dockerfile.strategy_engine -t agenttrader/strategy_engine:local ."; \
		echo "  docker build -f infra/Dockerfile.execution_engine -t agenttrader/execution_engine:local ."; \
		echo "  docker build -f infra/Dockerfile.ingest -t agenttrader/ingest:local ."; \
		echo "  docker build -f infra/Dockerfile.options_ingest -t agenttrader/options_ingest:local ."; \
		echo "  docker build -f infra/Dockerfile.stream_bridge -t agenttrader/stream_bridge:local ."; \
		echo "  docker build -f infra/Dockerfile.congressional_ingest -t agenttrader/congressional_ingest:local ."; \
		exit 0; \
	fi
	@if [[ ! -d "infra" ]]; then \
		echo "INFO: ./infra not found; nothing to build"; \
		exit 0; \
	fi
	@for f in infra/Dockerfile.*; do \
		[[ -f "$$f" ]] || continue; \
		name="$${f##*/}"; name="$${name#Dockerfile.}"; \
		tag="agenttrader/$${name}:local"; \
		echo "docker build -f $$f -t $$tag ."; \
		docker build -f "$$f" -t "$$tag" .; \
	done

frontend-build: ## Build the frontend application (npm run build)
	@echo "Building frontend application..."
	@if [ ! -d ./frontend ]; then echo "Error: ./frontend directory not found! Cannot build frontend."; exit 1; fi
	@npm --prefix frontend run build

guard: ## Run predeploy guardrails (fail-fast)
	@echo "== guard =="
	@if [[ ! -x "./scripts/ci_safety_guard.sh" ]]; then \
		echo "ERROR: missing ./scripts/ci_safety_guard.sh"; \
		exit 2; \
	fi
	@./scripts/ci_safety_guard.sh

deploy: ## Deploy v2 (prefers scripts/deploy_v2.sh; else kubectl apply)
	@echo "== deploy =="
	@if [[ -x "./scripts/deploy_v2.sh" ]]; then \
		args=(--namespace "$(NAMESPACE)" --k8s-dir "$(K8S_DIR)"); \
		[[ -n "$(PROJECT_ID)" ]] && args+=(--project "$(PROJECT_ID)"); \
		[[ -n "$(CONTEXT)" ]] && args+=(--expected-context "$(CONTEXT)"); \
		./scripts/deploy_v2.sh "$${args[@]}"; \
	else \
		if ! command -v kubectl >/dev/null 2>&1; then \
			echo "ERROR: kubectl not found and scripts/deploy_v2.sh missing"; \
			exit 2; \
		fi; \
		echo "kubectl apply -f $(K8S_DIR)"; \
		kargs=(); [[ -n "$(CONTEXT)" ]] && kargs+=(--context "$(CONTEXT)"); \
		kubectl "$${kargs[@]}" apply -f "$(K8S_DIR)"; \
	fi

report: ## Generate a deploy/report artifact (audit_artifacts/)
	@echo "== report =="
	@if [[ -x "./scripts/report_v2_deploy.sh" ]]; then \
		./scripts/report_v2_deploy.sh --namespace "$(NAMESPACE)"; \
	elif [[ -f "./scripts/report_v2_deploy.py" ]]; then \
		"$(PY)" ./scripts/report_v2_deploy.py --namespace "$(NAMESPACE)"; \
	else \
		echo "ERROR: missing scripts/report_v2_deploy.(sh|py)"; \
		exit 2; \
	fi

readiness: ## Fail-closed readiness gate (writes audit_artifacts/)
	@echo "== readiness =="
	@if [[ ! -x "./scripts/readiness_check.sh" ]]; then \
		echo "ERROR: missing ./scripts/readiness_check.sh"; \
		exit 2; \
	fi
	@./scripts/readiness_check.sh --namespace "$(NAMESPACE)"

status: ## Show k8s workload status + best-effort /ops/status
	@echo "== status =="
	@./scripts/kubectl_status.sh \
		--namespace "$(NAMESPACE)" \
		--mission-control-url "$(MISSION_CONTROL_URL)" \
		$(if $(CONTEXT),--context "$(CONTEXT)",)


git-status: ## Show current git status
	@echo "Checking repository git status..."
	@git status

logs: ## Tail logs for one workload (AGENT=<name>)
	@if [[ -z "$(AGENT)" ]]; then echo "ERROR: AGENT is required (e.g. make logs AGENT=strategy-engine)"; exit 2; fi
	@./scripts/kubectl_logs.sh \
		--namespace "$(NAMESPACE)" \
		--agent "$(AGENT)" \
		$(if $(CONTEXT),--context "$(CONTEXT)",)

rollout: ## Rollout guard (DEPLOY=<deployment> TAG=<image-tag>)
	@if [[ -z "$(DEPLOY)" ]]; then echo "ERROR: DEPLOY is required (e.g. make rollout DEPLOY=strategy-engine TAG=<sha>)"; exit 2; fi
	@if [[ -z "$(TAG)" ]]; then echo "ERROR: TAG is required (e.g. make rollout DEPLOY=strategy-engine TAG=<sha>)"; exit 2; fi
	@./scripts/rollout_guard.sh \
		--namespace "$(NAMESPACE)" \
		--deployment "$(DEPLOY)" \
		--tag "$(TAG)" \
		$(if $(CONTEXT),--context "$(CONTEXT)",)

scale: ## Scale a workload (AGENT=<name> REPLICAS=<n>)
	@if [[ -z "$(AGENT)" ]]; then echo "ERROR: AGENT is required"; exit 2; fi
	@if [[ -z "$(REPLICAS)" ]]; then echo "ERROR: REPLICAS is required"; exit 2; fi
	@./scripts/kubectl_scale.sh \
		--namespace "$(NAMESPACE)" \
		--agent "$(AGENT)" \
		--replicas "$(REPLICAS)" \
		$(if $(CONTEXT),--context "$(CONTEXT)",)

port-forward: ## Port-forward a service/pod (AGENT=<svc-or-pod> PORT=<local:remote>)
	@if [[ -z "$(AGENT)" ]]; then echo "ERROR: AGENT is required"; exit 2; fi
	@if [[ -z "$(PORT)" ]]; then echo "ERROR: PORT is required (e.g. PORT=8080:8080)"; exit 2; fi
	@if ! command -v kubectl >/dev/null 2>&1; then echo "ERROR: kubectl not found"; exit 2; fi
	@kargs=(); [[ -n "$(CONTEXT)" ]] && kargs+=(--context "$(CONTEXT)"); \
	if kubectl "$${kargs[@]}" -n "$(NAMESPACE)" get svc "$(AGENT)" >/dev/null 2>&1; then \
		echo "kubectl -n $(NAMESPACE) port-forward svc/$(AGENT) $(PORT)"; \
		kubectl "$${kargs[@]}" -n "$(NAMESPACE)" port-forward "svc/$(AGENT)" "$(PORT)"; \
	else \
		echo "INFO: service $(AGENT) not found; trying pod/$(AGENT)"; \
		echo "kubectl -n $(NAMESPACE) port-forward pod/$(AGENT) $(PORT)"; \
		kubectl "$${kargs[@]}" -n "$(NAMESPACE)" port-forward "pod/$(AGENT)" "$(PORT)"; \
	fi

clean: ## Remove local temp artifacts safely
	@echo "== clean =="
	@rm -rf \
		.pytest_cache .ruff_cache .mypy_cache \
		.coverage coverage.xml htmlcov \
		dist build \
		audit_artifacts/*.tmp \
		./frontend/dist 2>/dev/null || true
	@echo "OK: removed common local caches/artifacts"

# Day 1 Ops dry run (read-only): generates a dummy artifact set locally.
# Safety: does not deploy, does not scale, does not change kill-switch or AGENT_MODE.
day1-dry-run:
	@set -eu; \
	TS=$$(date -u +%Y%m%dT%H%M%SZ); \
	OUT="audit_artifacts/day1_dry_run/$${TS}"; \
	mkdir -p "$${OUT}"; \
	echo "agenttrader_v2_day1_dry_run=1" > "$${OUT}/meta.txt"; \
	echo "generated_utc=$${TS}" >> "$${OUT}/meta.txt"; \
	echo "git_sha=$$(git rev-parse HEAD 2>/dev/null || echo UNKNOWN)" >> "$${OUT}/meta.txt"; \
	echo "== running readiness_check (best-effort) =="; \
	./scripts/readiness_check.sh --skip-preflight || true; \
	cp -f audit_artifacts/readiness_report.md "$${OUT}/readiness_report.md" 2>/dev/null || true; \
	cp -f audit_artifacts/readiness_report.json "$${OUT}/readiness_report.json" 2>/dev/null || true; \
	echo "== running deploy report (best-effort) =="; \
	./scripts/report_v2_deploy.sh --namespace trading-floor || true; \
	cp -f audit_artifacts/deploy_report.md "$${OUT}/deploy_report.md" 2>/dev/null || true; \
	cp -f audit_artifacts/deploy_report.json "$${OUT}/deploy_report.json" 2>/dev/null || true; \
	echo "OK: wrote $${OUT}"