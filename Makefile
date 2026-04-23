.PHONY: all bootstrap venv run test test-only clean

all: venv

bootstrap: engine/durdraw/.git
engine/durdraw/.git:
	@echo "==> cloning Durdraw reference into engine/durdraw/"
	@mkdir -p engine
	git clone --depth=1 https://github.com/cmang/durdraw engine/durdraw

venv: .venv/bin/python
.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -e .

run: venv
	.venv/bin/python ansi_edit.py

# Full QA + perf suite.
test: venv
	.venv/bin/python -m tests.qa
	.venv/bin/python -m tests.perf

# Scenario subset by pattern. Usage:
#   make test-only PAT=undo
test-only: venv
	.venv/bin/python -m tests.qa $(PAT)

clean:
	rm -rf .venv build dist *.egg-info
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
