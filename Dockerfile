FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=7860

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .

RUN mkdir -p data/raw reports .streamlit && \
    chown -R user:user /app

EXPOSE 7860 8000

COPY --chown=user:user entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER user

ENTRYPOINT ["/entrypoint.sh"]
