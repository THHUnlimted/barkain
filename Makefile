.PHONY: help demo-check demo-warm verify-counts

help:
	@echo "Barkain make targets:"
	@echo "  demo-check     — hit dev backend /health + resolve an evergreen UPC,"
	@echo "                   verify ≥7 of 9 retailers respond w/ prices in 15s."
	@echo "                   Exits 0 (healthy) or 1 (something hard-down)."
	@echo "                   Pass ARGS=\"--no-cache\" to bypass Redis replay."
	@echo "                   Pass ARGS=\"--remote-containers=ec2\" to pre-flight"
	@echo "                   EC2 container /health (needs EC2_CONTAINER_BASE_URL"
	@echo "                   or per-retailer {RETAILER}_CONTAINER_URL env vars)."
	@echo "  demo-warm      — pre-warm Redis + PG pool + Gemini cache by running"
	@echo "                   the demo-warm UPC list through the full scan flow."
	@echo "                   Run ~30 min before F&F arrives."
	@echo "  verify-counts  — print canonical backend + iOS test counts. Run"
	@echo "                   before updating any guiding-doc test count to"
	@echo "                   pin numbers (see docs/TESTING.md § Conventions)."

demo-check:
	PYTHONPATH=backend python3 scripts/demo_check.py $(ARGS)

demo-warm:
	PYTHONPATH=backend python3 scripts/demo_warm.py

verify-counts:
	@bash scripts/verify_test_counts.sh
