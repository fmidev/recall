FROM python:3.12.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/

# Set the working directory
WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN uv pip install --system --require-hashes -r requirements.txt
COPY gen_cmaps.py run.sh /app/

RUN chmod +x run.sh
CMD ["./run.sh"]
