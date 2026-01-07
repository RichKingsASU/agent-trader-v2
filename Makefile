.PHONY: report report-skip-health

report:
	./scripts/report_v2_deploy.sh

report-skip-health:
	./scripts/report_v2_deploy.sh --skip-health

