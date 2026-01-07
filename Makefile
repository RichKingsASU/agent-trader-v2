.PHONY: report report-skip-health day1-dry-run

report:
	./scripts/report_v2_deploy.sh

report-skip-health:
	./scripts/report_v2_deploy.sh --skip-health

day1-dry-run:
	@bash -euo pipefail -c '\
	ts="$$(date -u +'"'"'%Y%m%dT%H%M%SZ'"'"')"; \
	base="audit_artifacts/day1_dry_run/$$ts"; \
	mkdir -p "$$base"; \
	./scripts/readiness_check.sh --allow-no-cluster --output-dir "$$base/readiness_check"; \
	python3 scripts/report_v2_deploy.py --skip-health --output-dir "$$base/deploy_report"; \
	./scripts/capture_config_snapshot.sh --output-dir "$$base/config_snapshot"; \
	./scripts/generate_blueprint.sh --output-dir "$$base/blueprint"; \
	echo "OK: day1 dry run artifacts under $$base"'

