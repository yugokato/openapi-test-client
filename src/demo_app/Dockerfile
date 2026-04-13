# Build (from the project root):
#   docker build -f src/demo_app/Dockerfile . -t demo_app
#
# Run:
#   docker run -p 8000:8000 demo_app

FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml ./
COPY src/demo_app ./src/demo_app

RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 uv pip install --system ".[app]"

RUN useradd -m demo && chown -R demo:demo /app
USER demo

CMD ["fastapi", "run", "src/demo_app"]
