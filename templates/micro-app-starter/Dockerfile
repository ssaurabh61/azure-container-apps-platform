# Lightweight, zero-dependency Python 3.12 Alpine runtime
FROM python:3.12-alpine

WORKDIR /app

# Create unprivileged application user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy application assets and backend code
COPY server.py ./
COPY src/ ./src/

# Ensure persistent storage mount point exists with permissions
RUN mkdir -p /data && chown -R appuser:appgroup /data /app

# Switch to non-root user
USER appuser

ENV PORT=8080 \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

CMD ["python3", "server.py"]
