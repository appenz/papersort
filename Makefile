.PHONY: run clean showlayout test dedup

run:
	uv run main.py

run-test-inbox:
	uv run main.py --inbox local:inbox --verify --update


showlayout:
	uv run main.py --showlayout

dedup:
	uv run main.py --deduplicate

test:
	uv run pytest tests/ -v

clean:
	rm -f ~/Library/Application\ Support/papersort/metadata.db
