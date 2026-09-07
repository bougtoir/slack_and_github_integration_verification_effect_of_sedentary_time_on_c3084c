.PHONY: build run test clean

build:
	docker compose build

run:
	docker compose exec sandbox python -m paper_sandbox.cli --input examples/sample_input.json

test:
	python -m pytest tests/ -q

clean:
	rm -rf workspace/output
