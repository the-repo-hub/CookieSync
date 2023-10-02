run:
	python reso_auto/main.py

lint:
	poetry run flake8 reso_auto

mypy:
	poetry run mypy reso_auto