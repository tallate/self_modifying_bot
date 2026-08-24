ARG PYTHON_BASE_IMAGE=dockerproxy.net/library/python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

ARG HERMES_REPOSITORY=https://github.com/NousResearch/hermes-agent.git

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    SELF_MODIFYING_BOT_HOME=/var/lib/self_modifying_bot

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "hermes-agent @ git+${HERMES_REPOSITORY}"
COPY . .

RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /var/lib/self_modifying_bot \
    && chown -R bot:bot /app /var/lib/self_modifying_bot
USER bot

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
