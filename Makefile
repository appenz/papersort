.PHONY: run clean showlayout test dedup

run:
	uv run papersort.py

run-test-inbox:
	uv run papersort.py --inbox local:inbox --verify --update


showlayout:
	uv run papersort.py --showlayout

dedup:
	uv run papersort.py --deduplicate

test:
	uv run pytest tests/ -v

clean:
	rm -f ~/Library/Application\ Support/papersort/metadata.db
