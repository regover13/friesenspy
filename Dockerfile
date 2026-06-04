FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -u 1001 -m -s /bin/bash friesenspy
USER friesenspy
WORKDIR /opt/friesenspy

COPY --chown=friesenspy:friesenspy requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=friesenspy:friesenspy app/ ./app/

ENV PATH="/home/friesenspy/.local/bin:$PATH"
ENV DB_PATH=/opt/friesenspy/data/friesenspy.db
# SECRET_KEY wird über config.env gesetzt (Pflichtfeld — kein Fallback)

EXPOSE 8091
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091", "--log-level", "info"]
