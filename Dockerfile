# Hearth-Core, standalone (development / CI).
#
# In production Hearth-Core is not run from this image: Hearth-backend's space
# template (templates/space/Dockerfile) copies it into the single hardened space
# image alongside the other engine services. This Dockerfile exists so the
# component can be built and tested on its own.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5010 \
    HEARTH_STATE_DIR=/var/lib/hearth \
    HEARTH_SKIP_BOOT_INSTALL=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git gh nodejs npm ca-certificates curl \
 && npm install -g @anthropic-ai/claude-code \
 && rm -rf /var/lib/apt/lists/* /root/.npm

RUN useradd --create-home --uid 10001 engine && mkdir -p /var/lib/hearth && chown engine /var/lib/hearth

WORKDIR /opt/hearth-core
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

USER engine
EXPOSE 5010
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://127.0.0.1:5010/health || exit 1
CMD ["python", "server.py"]
