.PHONY: help demo-check demo-warm verify-counts bench-misc-retailer

help:
	@echo "Barkain make targets:"
	@echo "  demo-check          — hit dev backend /health + resolve an evergreen UPC,"
	@echo "                        verify ≥5 of 9 retailers respond w/ prices in 15s."
	@echo "                        Exits 0 (healthy) or 1 (something hard-down)."
	@echo "                        Pass ARGS=\"--no-cache\" to bypass Redis replay."
	@echo "                        Pass ARGS=\"--remote-containers=ec2\" to pre-flight"
	@echo "                        EC2 container /health (needs EC2_CONTAINER_BASE_URL"
	@echo "                        or per-retailer {RETAILER}_CONTAINER_URL env vars)."
	@echo "  demo-warm           — pre-warm Redis + PG pool + Gemini cache by running"
	@echo "                        the demo-warm UPC list through the full scan flow."
	@echo "                        Run ~30 min before F&F arrives."
	@echo "  verify-counts       — print canonical backend + iOS test counts. Run"
	@echo "                        before updating any guiding-doc test count to"
	@echo "                        pin numbers (see docs/TESTING.md § Conventions)."
	@echo "  bench-misc-retailer — run the Step 3n misc-retailer 50-SKU pet-vertical"
	@echo "                        bench against Serper Shopping. Writes per-SKU +"
	@echo "                        aggregate JSON to scripts/bench_results/. Exit"
	@echo "                        codes: 0 (≥80%% pass), 2 (below pass), 3 (below"
	@echo "                        75%% alert). ~100 Serper credits per run (\$$0.10)."

demo-check:
	PYTHONPATH=backend python3 scripts/demo_check.py $(ARGS)

demo-warm:
	PYTHONPATH=backend python3 scripts/demo_warm.py

verify-counts:
	@bash scripts/verify_test_counts.sh

bench-misc-retailer:
	@mkdir -p scripts/bench_results
	@PYTHONPATH=backend python3 scripts/bench_misc_retailer.py \
		--panel scripts/bench_data/misc_retailer_panel_v1.json \
		--out scripts/bench_results/misc_retailer_$$(date -u +%Y%m%dT%H%M%SZ).json $(ARGS)
