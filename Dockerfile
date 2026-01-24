FROM ghcr.io/astral-sh/uv:0.6.17-python3.13-bookworm

RUN useradd -m devuser
RUN mkdir -p /app
RUN chown devuser:devuser /app

WORKDIR /app

# Ensure Python output is not buffered (visible immediately in docker logs)
ENV PYTHONUNBUFFERED=1

USER devuser

# Set up the python environment with uv
RUN uv init
RUN uv add dropbox google-api-python-client google-auth google-auth-oauthlib mistralai openai textual
RUN uv sync

# Copy source code
COPY --chown=devuser:devuser main.py .
COPY --chown=devuser:devuser papersort/ papersort/
COPY --chown=devuser:devuser models/ models/
COPY --chown=devuser:devuser storage/ storage/
COPY --chown=devuser:devuser utils/ utils/
COPY --chown=devuser:devuser workflows/ workflows/

CMD ["uv", "run", "main.py", "--ingest"]
