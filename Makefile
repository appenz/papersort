.PHONY: run clean showlayout

run:
	uv run papersort.py

showlayout:
	uv run papersort.py --showlayout

clean:
	rm -f ~/Library/Application\ Support/papersort/metadata.db
