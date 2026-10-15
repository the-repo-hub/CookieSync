PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
NODE ?= node
ARGS ?=

.PHONY: run run_server test test-server test-extension build-extension release-extension

run run_server:
	$(PYTHON) -m cookieserver.manage runserver $(ARGS)

test: test-server test-extension

test-server:
	$(PYTHON) -m pytest -q cookieserver/tests tests

test-extension:
	$(NODE) --test

build-extension:
	$(PYTHON) build_extension.py

release-extension: test
	$(PYTHON) build_extension.py --release
