FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# Dépendances d'abord, pour profiter du cache des couches Docker.
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --no-install-project

COPY src ./src
COPY prompts ./prompts
RUN uv sync --no-dev

EXPOSE 8000
# Lancé directement depuis le venv : le service tourne sous l'utilisateur de l'hôte (voir compose),
# qui n'a pas à écrire dans /app.
CMD ["uvicorn", "demandes.adaptateurs.entrants.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
