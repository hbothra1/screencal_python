.PHONY: build run test clean

build:
	python3 -m pip install --upgrade pip
	python3 -m pip install -r requirements.txt

run:
	@if [ "$(STUB)" = "noevent" ]; then \
		USE_STUB_NOEVENT=1 python3 -m src.app; \
	elif [ "$(STUB)" = "1" ]; then \
		USE_STUB=1 python3 -m src.app; \
	else \
		python3 -m src.app; \
	fi

test:
	python3 -m pytest tests/ -v

clean:
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".DS_Store" -delete 2>/dev/null || true

