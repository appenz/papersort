.PHONY: run clean showlayout test

run:
	uv run papersort.py

showlayout:
	uv run papersort.py --showlayout

test:
	uv run pytest tests/ -v

clean:
	rm -f ~/Library/Application\ Support/papersort/metadata.db
