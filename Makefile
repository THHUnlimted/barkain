.PHONY: help demo-check demo-warm

help:
	@echo "Barkain make targets:"
	@echo "  demo-check  — hit dev backend /health + resolve an evergreen UPC,"
	@echo "                verify ≥7 of 9 retailers respond w/ prices in 15s."
	@echo "                Exits 0 (healthy) or 1 (something hard-down)."
	@echo "  demo-warm   — pre-warm Redis + PG pool + Gemini cache by running"
	@echo "                the demo-warm UPC list through the full scan flow."
	@echo "                Run ~30 min before F&F arrives."

demo-check:
	PYTHONPATH=backend python3 scripts/demo_check.py

demo-warm:
	PYTHONPATH=backend python3 scripts/demo_warm.py
