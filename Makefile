.PHONY: setup test dev api web build run docker

setup:            ## install everything
	git submodule update --init
	uv sync
	npm --prefix web ci

test:             ## all tests (both upstream suites + Saarthi), offline
	cd vendor/nse-trader-skill && python3 -m unittest discover -s tests -q
	cd vendor/claude-trading-skills-india && python3 -m unittest discover -s tests -q
	uv run pytest -q
	npm --prefix web run build

api:              ## API on :8000 (dev)
	uv run uvicorn backend.api.app:app --host 127.0.0.1 --port 8000

web:              ## UI dev server on :5173 (proxies /api to :8000)
	npm --prefix web run dev

build:            ## production UI build, served by the API at /
	npm --prefix web run build

run: build        ## the whole app on http://127.0.0.1:8000
	uv run uvicorn backend.api.app:app --host 127.0.0.1 --port 8000

docker:           ## the whole app in Docker on http://127.0.0.1:8000
	docker compose up --build
