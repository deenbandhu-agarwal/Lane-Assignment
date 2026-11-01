.PHONY: setup test test-docker up bench dump

setup:            ## local venv on free-threaded Python 3.14t
	uv venv --python 3.14t .venv
	uv sync

test:             ## run tests locally
	uv run pytest -q

test-docker:      ## the reviewer's one command
	docker compose run --rm --build test

up:
	docker compose up --build

bench:            ## regenerate bench/results/*
	docker compose run --rm --build bench

dump:             ## make dump FILE=data/sst/L0/000001.sst
	uv run tsdb-dump $(FILE)
