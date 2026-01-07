.PHONY: report report-skip-health
.PHONY: day1-dry-run

report:
	./scripts/report_v2_deploy.sh

report-skip-health:
	./scripts/report_v2_deploy.sh --skip-health

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

