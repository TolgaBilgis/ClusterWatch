FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY clusterwatch ./clusterwatch
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 clusterwatch \
    && mkdir -p /app/data \
    && chown -R clusterwatch:clusterwatch /app
USER clusterwatch

EXPOSE 8000
CMD ["clusterwatch-controller"]

