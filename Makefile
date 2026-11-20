.PHONY: setup up down logs seed demo test local clean-data openapi
setup up:
	./scripts/setup.sh
down:
	./scripts/compose.sh down
logs:
	./scripts/compose.sh logs -f --tail=100
seed:
	./scripts/compose.sh run --rm bootstrap
demo:
	python3 scripts/demo.py
test:
	cd backend && ../.venv/bin/python -m pytest -q
	cd frontend && npm test && npm run build
local:
	./scripts/local-demo.sh
clean-data:
	./scripts/cleanup.sh --confirm
openapi:
	cd backend && ../.venv/bin/python -m app.cli openapi > ../shared/contracts/openapi.json
