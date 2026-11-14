# Runs the customcbot web app. Ollama runs separately; see docker-compose.yml.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# libgl1 and libglib2.0-0 are needed by the OCR library.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV CUSTOMCBOT_DATA_DIR=/data
VOLUME /data
EXPOSE 8765
CMD ["uv", "run", "--no-dev", "customcbot", "--host", "0.0.0.0", "--no-browser"]
