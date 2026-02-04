.PHONY: install example test lint clean

# ── Setup ─────────────────────────────────────────────────
install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pip install fastapi uvicorn

# ── Example App ───────────────────────────────────────────
example:
	TRACELY_API_KEY=$(TRACELY_API_KEY) TRACELY_ENDPOINT=$(or $(TRACELY_ENDPOINT),http://localhost:8000) .venv/bin/python examples/fastapi_app.py

# ── Tests ─────────────────────────────────────────────────
test:
	.venv/bin/pytest tests/ -v

# ── Clean ─────────────────────────────────────────────────
clean:
	rm -rf .venv dist *.egg-info src/*.egg-info
