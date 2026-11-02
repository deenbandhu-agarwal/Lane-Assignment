.PHONY: setup test test-docker chat chat-offline seed eval experiment

setup:            ## local venv on Python 3.13
	uv sync

test:             ## offline tests (fake model, no network)
	uv run pytest -q

test-docker:      ## the reviewer's one command
	docker compose run --rm --build test

chat:             ## interactive agent: real model + real GitHub sandbox
	uv run python -m agent.cli

chat-offline:     ## real model, in-memory sandbox repo (no GitHub calls)
	uv run python -m agent.cli --offline-github

seed:             ## fill the sandbox repo (dry run; add ARGS=--apply)
	uv run python scripts/seed_sandbox.py $(ARGS)

eval:             ## golden set through the real agent (model from .env + sandbox repo) -> eval/results/
	uv run python eval/run_eval.py

experiment:       ## retrieval experiment bm25 vs vector vs hybrid (no LLM) -> eval/results/
	uv run python eval/experiment.py
