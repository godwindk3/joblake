FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /opt/joblake
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 joblake
COPY pyproject.toml requirements.txt constraints.txt ./
COPY src ./src
RUN python -m pip install -r requirements.txt \
    && python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*
COPY alembic.ini ./
COPY migrations ./migrations
COPY configs ./configs
COPY orchestration/standalone/config.yaml ./orchestration/standalone/config.yaml
RUN mkdir -p data/state output && chown -R joblake:joblake data output
USER joblake
RUN python -m cloakbrowser install
ENTRYPOINT ["python", "-m", "joblake.standalone"]
CMD ["schedule"]
