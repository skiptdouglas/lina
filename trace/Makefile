# TRACE — developer entry points.
.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose
PY := python3

.PHONY: help init up down restart logs ps build test test-integration lint fmt-check \
        backend-deps frontend-deps frontend-build demo-data smoke clean nuke

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

init: ## Create .env and the log signing key (never overwrites existing ones)
	@$(PY) scripts/init_env.py --root .
	@if [ ! -f deploy/keys/log-signing-key.pem ]; then \
	  $(PY) scripts/generate_signing_key.py --out deploy/keys/log-signing-key.pem; \
	else \
	  echo "deploy/keys/log-signing-key.pem already exists — leaving it alone."; \
	fi

up: ## Start the stack (waits for dependencies to become healthy)
	$(COMPOSE) up -d --build
	@echo "UI  http://localhost:$${TRACE_UI_PORT:-3000}"
	@echo "API http://localhost:$${TRACE_API_PORT:-8000}/docs"

down: ## Stop the stack, keep volumes
	$(COMPOSE) down

restart: down up ## Restart the stack

logs: ## Tail logs (make logs SERVICE=trace-api)
	$(COMPOSE) logs -f $(SERVICE)

ps: ## Show service status and health
	$(COMPOSE) ps

build: ## Rebuild images
	$(COMPOSE) build

backend-deps: ## Create the backend virtualenv
	cd backend && $(PY) -m venv .venv && ./.venv/bin/pip install -e '.[dev]'

test: ## Run the backend test-suite (no infrastructure required)
	cd backend && ./.venv/bin/python -m pytest -q

test-integration: ## Run tests that need live MinIO (see tests/integration)
	cd backend && ./.venv/bin/python -m pytest -q -m integration

lint: ## Lint the backend
	cd backend && ./.venv/bin/python -m ruff check app tests

fmt-check: ## Check backend formatting
	cd backend && ./.venv/bin/python -m ruff format --check app tests

frontend-deps: ## Install UI dependencies
	cd frontend && npm install

frontend-build: ## Typecheck and build the UI
	cd frontend && npm run build

demo-data: ## Generate synthetic telemetry for CASE-DEMO-001 into sample-data/
	$(PY) scripts/generate_demo_data.py --out sample-data/case-demo-001

signing-key: ## Generate the Ed25519 key that signs Merkle tree heads
	$(PY) scripts/generate_signing_key.py --out deploy/keys/log-signing-key.pem

verify-proof: ## Verify a proof bundle offline (make verify-proof BUNDLE=proof.json [FILE=evidence.log])
	@$(PY) scripts/verify_anchor.py $(BUNDLE) $(if $(FILE),--evidence-file $(FILE),) $(if $(KEY_ID),--expect-key-id $(KEY_ID),)

smoke: ## Drive the Sprint 1 workflow against a running stack (needs TRACE_TOKEN)
	./scripts/smoke_sprint1.sh

clean: ## Remove build artefacts and local databases
	rm -rf backend/.pytest_cache backend/.ruff_cache frontend/dist
	find backend -name '__pycache__' -type d -prune -exec rm -rf {} +

nuke: ## Stop the stack AND delete all volumes (destroys stored evidence)
	@read -p "This deletes all stored evidence and cases. Type 'yes' to continue: " ok && \
	  [ "$$ok" = "yes" ] && $(COMPOSE) down -v || echo "aborted"
