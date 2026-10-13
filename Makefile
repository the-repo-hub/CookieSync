run:
	python -m src.main
run_server:
	python -m resoserver.start
test:
	python -m unittest

.PHONY: build-extension
build-extension:
	python3 build_extension.py
