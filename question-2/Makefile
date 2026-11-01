.PHONY: setup test test-docker

setup:            ## local venv on Python 3.13
	uv sync

test:             ## offline tests (fake model, no network)
	uv run pytest -q

test-docker:      ## the reviewer's one command
	docker compose run --rm --build test
