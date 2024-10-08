FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY . /app
RUN pip install -U pip \
    && pip install .

CMD ["gunicorn", "recall.app:server", "-b", "0.0.0.0:8050"]
