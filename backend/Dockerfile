FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py tasks.json tasker_reqs.py collection_tasks.json item_ids.json skill_tasks.py quests.json verify.py ./
COPY icons ./icons
ENV DB_PATH=/data/afk.db
EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "-k", "gthread", "--threads", "8", "--timeout", "60", "app:app"]
