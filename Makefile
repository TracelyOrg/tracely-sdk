.PHONY: install example test lint clean release

# ── Setup ─────────────────────────────────────────────────
install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pip install fastapi uvicorn

# ── Example App ───────────────────────────────────────────
example:
	TRACELY_API_KEY=$(TRACELY_API_KEY) TRACELY_ENDPOINT=$(or $(TRACELY_ENDPOINT),http://localhost:8000) .venv/bin/python examples/fastapi_app.py

# ── Tests ─────────────────────────────────────────────────
test:
	.venv/bin/pytest tests/ -v

# ── Release ───────────────────────────────────────────────
release:
ifndef VERSION
	$(error VERSION is required. Usage: make release VERSION=0.1.0)
endif
	git tag -a "v$(VERSION)" -m "Release v$(VERSION)"
	git push origin "v$(VERSION)"

# ── Clean ─────────────────────────────────────────────────
clean:
	rm -rf .venv dist *.egg-info src/*.egg-info
