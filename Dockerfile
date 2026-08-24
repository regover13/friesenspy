FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -u 1001 -m -s /bin/bash friesenspy
USER friesenspy
WORKDIR /opt/friesenspy

COPY --chown=friesenspy:friesenspy requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=friesenspy:friesenspy app/ ./app/
# scripts/ gehoert ins Image, weil der woechentliche AIP-Job in app/poller.py
# `from scripts.aip_bestand import lauf` macht. Ohne diese Zeile scheitert er mit
# ImportError -- und zwar lautlos, denn der Job faengt jede Exception ab. Der
# Kartenbestand waere dann einfach nie aufgefrischt. tests/test_aip_api.py haelt
# das fest.
COPY --chown=friesenspy:friesenspy scripts/ ./scripts/

ENV PATH="/home/friesenspy/.local/bin:$PATH"
ENV DB_PATH=/opt/friesenspy/data/friesenspy.db
# SECRET_KEY wird über config.env gesetzt (Pflichtfeld — kein Fallback)

EXPOSE 8091
# --proxy-headers seit 2026-08-19 (Security-Audit):
# Ohne die Option ist request.client.host fuer JEDE Anfrage 127.0.0.1 -- die
# Adresse von nginx, nicht die des Besuchers. Das hatte zwei Folgen:
#
#   1. Die Login-Bremse (5 Fehlversuche/60 s, main.py) zaehlte GLOBAL statt
#      je Adresse. Ein Fremder konnte mit fuenf Fehlversuchen den echten
#      Admin fuer das Zeitfenster aussperren.
#   2. Die Warnung "Fehlgeschlagener Login von %s" nannte immer 127.0.0.1 --
#      die Adresse des Angreifers war forensisch verloren.
#
# --forwarded-allow-ips begrenzt das Vertrauen auf nginx; ohne diese Angabe
# wuerde uvicorn den Header von jedem Absender glauben, und dann koennte
# sich jeder eine beliebige Herkunft ausdenken.
#
# Warum nicht nur 127.0.0.1: nginx laeuft auf dem Host und erreicht den
# Container ueber die Docker-Bruecke -- aus Sicht von uvicorn kommt die
# Verbindung also von 172.25.0.1, nicht von Loopback. Mit 127.0.0.1 allein
# verwarf uvicorn den Header und protokollierte weiter die Gateway-Adresse
# (beim ersten Anlauf am 2026-08-19 genau so passiert). 172.16.0.0/12 deckt
# alle Docker-Netze ab und bleibt gueltig, wenn ein Netz neu angelegt wird
# und eine andere Nummer bekommt.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091", \
     "--log-level", "info", \
     "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1,172.16.0.0/12"]
