FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SELF_MODIFYING_BOT_HOME=/var/lib/self_modifying_bot

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /var/lib/self_modifying_bot \
    && chown -R bot:bot /app /var/lib/self_modifying_bot
USER bot

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
