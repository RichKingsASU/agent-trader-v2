SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

# =========================
# AgentTrader v2 "Trading Floor" workflow
# Single entrypoint for build/deploy/ops (safe + deterministic)
# =========================

# ---- Overridable configuration (required) ----
NAMESPACE ?= default
K8S_DIR ?= k8s
PROJECT_ID ?=
REGION ?=
CONTEXT ?=
MISSION_CONTROL_URL ?= http://agenttrader-mission-control

# ---- Internal defaults ----
LABEL_SELECTOR ?= app.kubernetes.io/part-of=agent-trader-v2
TIMEOUT ?= 300s
PYTEST_ARGS ?=

CTX_FLAG :=
ifneq ($(strip $(CONTEXT)),)
CTX_FLAG := --context $(CONTEXT)
endif

.PHONY: help fmt lint test build deploy guard report readiness status logs scale port-forward clean

##@ General
help: ## List available targets
	@awk 'BEGIN {FS=":.*##"; \
		print "AgentTrader v2 — Trading Floor Make targets"; \
		print ""; \
		print "Usage:"; \
		print "  make <target> [VAR=value]"; \
		print ""; \
		print "Common vars (override as needed):"; \
		print "  NAMESPACE=$(NAMESPACE)"; \
		print "  CONTEXT=$(CONTEXT)"; \
		print "  K8S_DIR=$(K8S_DIR)"; \
		print "  MISSION_CONTROL_URL=$(MISSION_CONTROL_URL)"; \
		print ""; \
		print "Targets:" \
	} \
	/^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-16s %s\n", $$1, $$2} \
	/^##@/ {printf "\n%s\n", substr($$0,5)}' $(MAKEFILE_LIST)

##@ Quality
fmt: ## Best-effort formatting (python + yaml)
	@echo "== fmt (best-effort) =="
	@if command -v python3 >/dev/null 2>&1; then \
		if python3 -m ruff --version >/dev/null 2>&1; then \
			echo "ruff format"; python3 -m ruff format . || true; \
		elif python3 -m black --version >/dev/null 2>&1; then \
			echo "black"; python3 -m black . || true; \
		else \
			echo "SKIP: python formatter not found (install: ruff or black)"; \
		fi; \
	else \
		echo "SKIP: python3 not found"; \
	fi
	@if command -v yamlfmt >/dev/null 2>&1; then \
		echo "yamlfmt"; yamlfmt -quiet -path . || true; \
	else \
		echo "SKIP: yamlfmt not found (install: yamlfmt)"; \
	fi

lint: ## Best-effort lint checks
	@echo "== lint (best-effort) =="
	@if command -v python3 >/dev/null 2>&1; then \
		if python3 -m ruff --version >/dev/null 2>&1; then \
			echo "ruff check"; python3 -m ruff check . || true; \
		else \
			echo "SKIP: ruff not found (install: ruff)"; \
		fi; \
		echo "compileall"; python3 -m compileall backend agenttrader tests >/dev/null 2>&1 || true; \
	else \
		echo "SKIP: python3 not found"; \
	fi
	@if command -v yamllint >/dev/null 2>&1; then \
		echo "yamllint"; yamllint -s . || true; \
	else \
		echo "SKIP: yamllint not found (optional)"; \
	fi

test: ## Run python tests (if present)
	@echo "== test =="
	@if [ -d tests ]; then \
		if command -v python3 >/dev/null 2>&1 && python3 -m pytest --version >/dev/null 2>&1; then \
			python3 -m pytest -q $(PYTEST_ARGS); \
		else \
			echo "SKIP: pytest not available (install: pip install pytest)"; \
		fi; \
	else \
		echo "SKIP: ./tests not found"; \
	fi

##@ Build / Deploy
build: ## Build images locally if possible, else print instructions
	@echo "== build =="
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "SKIP: docker not installed. To build images, install Docker and ensure the daemon is running."; \
		echo "Dockerfiles: infra/Dockerfile.*"; \
		exit 0; \
	fi
	@if ! docker info >/dev/null 2>&1; then \
		echo "SKIP: docker daemon not reachable. Start Docker Desktop / dockerd and retry."; \
		exit 0; \
	fi
	@echo "Building infra/Dockerfile.* as local tags (agenttrader/<name>:local)"
	@set -e; \
	shopt -s nullglob; \
	for df in infra/Dockerfile.*; do \
		name="$${df##*/}"; name="$${name#Dockerfile.}"; \
		tag="agenttrader/$${name}:local"; \
		echo ""; \
		echo "docker build -f $${df} -t $${tag} ."; \
		docker build -f "$${df}" -t "$${tag}" .; \
	done

guard: ## Run pre-deploy guardrails (no execution)
	@echo "== guard =="
	@if [ -x scripts/predeploy_guard.sh ]; then \
		NAMESPACE="$(NAMESPACE)" K8S_DIR="$(K8S_DIR)" scripts/predeploy_guard.sh; \
	else \
		echo "ERROR: scripts/predeploy_guard.sh missing. Run: make guard (after pulling latest)"; \
		exit 2; \
	fi

deploy: ## Deploy via scripts/deploy_v2.sh if present, else kubectl apply
	@echo "== deploy =="
	@if [ -x scripts/deploy_v2.sh ]; then \
		echo "Using scripts/deploy_v2.sh (uses current kubectl context)"; \
		NS="$(NAMESPACE)" PROJECT="$(PROJECT_ID)" REGION="$(REGION)" scripts/deploy_v2.sh; \
	else \
		if ! command -v kubectl >/dev/null 2>&1; then \
			echo "ERROR: kubectl not installed; cannot deploy manifests from $(K8S_DIR)/"; \
			exit 2; \
		fi; \
		echo "kubectl $(CTX_FLAG) apply -f $(K8S_DIR)/"; \
		kubectl $(CTX_FLAG) apply -f "$(K8S_DIR)/"; \
	fi

report: ## Generate deployment report (kubectl read-only)
	@echo "== report =="
	@if [ -x scripts/report_v2_deploy.sh ]; then \
		if [ -n "$(strip $(CONTEXT))" ]; then \
			scripts/report_v2_deploy.sh --namespace "$(NAMESPACE)" --context "$(CONTEXT)"; \
		else \
			scripts/report_v2_deploy.sh --namespace "$(NAMESPACE)"; \
		fi; \
	elif [ -f scripts/report_v2_deploy.py ] && command -v python3 >/dev/null 2>&1; then \
		python3 scripts/report_v2_deploy.py --namespace "$(NAMESPACE)" $(if $(strip $(CONTEXT)),--context "$(CONTEXT)",); \
	else \
		echo "ERROR: report generator not found (expected scripts/report_v2_deploy.sh or scripts/report_v2_deploy.py)"; \
		exit 2; \
	fi

readiness: ## Readiness check (fails if cluster unreachable / workloads not ready)
	@echo "== readiness =="
	@if [ -x scripts/readiness_check.sh ]; then \
		NAMESPACE="$(NAMESPACE)" CONTEXT="$(CONTEXT)" LABEL_SELECTOR="$(LABEL_SELECTOR)" TIMEOUT="$(TIMEOUT)" MISSION_CONTROL_URL="$(MISSION_CONTROL_URL)" scripts/readiness_check.sh; \
	else \
		echo "ERROR: scripts/readiness_check.sh missing."; \
		exit 2; \
	fi

##@ Ops
status: ## kubectl status + best-effort /ops/status curl
	@echo "== status =="
	@NAMESPACE="$(NAMESPACE)" CONTEXT="$(CONTEXT)" LABEL_SELECTOR="$(LABEL_SELECTOR)" MISSION_CONTROL_URL="$(MISSION_CONTROL_URL)" scripts/kubectl_status.sh || true
	@if command -v curl >/dev/null 2>&1; then \
		url="$(MISSION_CONTROL_URL)"; \
		echo ""; echo "== mission control: $${url}/ops/status (best-effort) =="; \
		curl -fsS --max-time 2 "$${url}/ops/status" || echo "WARN: unable to reach $${url}/ops/status"; \
	else \
		echo ""; echo "SKIP: curl not installed (cannot probe $(MISSION_CONTROL_URL)/ops/status)"; \
	fi

logs: ## Tail logs for one workload (requires AGENT=<name>)
	@AGENT="$(AGENT)" NAMESPACE="$(NAMESPACE)" CONTEXT="$(CONTEXT)" scripts/kubectl_logs.sh

scale: ## Scale a workload (requires AGENT=<name> REPLICAS=<n>)
	@AGENT="$(AGENT)" REPLICAS="$(REPLICAS)" NAMESPACE="$(NAMESPACE)" CONTEXT="$(CONTEXT)" scripts/kubectl_scale.sh

port-forward: ## Port-forward a service (requires AGENT=<svc> PORT=<local:remote>)
	@if [ -z "$(strip $(AGENT))" ] || [ -z "$(strip $(PORT))" ]; then \
		echo "ERROR: require AGENT=<service> and PORT=<local:remote> (example: make port-forward AGENT=marketdata-mcp-server PORT=8080:80)"; \
		exit 2; \
	fi
	@if ! command -v kubectl >/dev/null 2>&1; then \
		echo "ERROR: kubectl not installed"; \
		exit 2; \
	fi
	@echo "kubectl $(CTX_FLAG) -n $(NAMESPACE) port-forward svc/$(AGENT) $(PORT)"
	@kubectl $(CTX_FLAG) -n "$(NAMESPACE)" port-forward "svc/$(AGENT)" "$(PORT)"

clean: ## Remove local temp artifacts safely
	@echo "== clean =="
	@rm -rf \
		audit_artifacts/deploy_report.md \
		audit_artifacts/deploy_report.json \
		.pytest_cache \
		.ruff_cache 2>/dev/null || true
	@echo "OK"

