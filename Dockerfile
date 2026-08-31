FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# `iputils-ping` n'est pas un confort de diagnostic : la sonde PING lance le
# binaire `ping` (app/tasks/probes.py), et la découverte réseau y retombe pour
# toute méthode qui n'est pas TCP-avec-port. Sans lui, TOUT moniteur ICMP rend
# DOWN quelle que soit la cible, et un balayage CIDR ne provisionne jamais rien.
# Le README vend pourtant « ICMP ping » parmi les types de moniteurs.
#
# Le défaut est resté invisible parce que l'image n'était jamais exercée : la CI
# la construisait puis la jetait, exactement comme pour `static/` plus haut. Le
# seul contrôle qui le signalait, `test_run_probe_ping_loopback_is_up`, était
# rouge sur le runner et se lisait comme un défaut du runner.
#
# ATTENTION, ceci ne suffit pas à faire marcher ICMP. L'image tourne en uid
# 1000, et podman pose `net.ipv4.ping_group_range = 0 0` dans le netns du
# conteneur : le binaire est là et échoue quand même, en `Operation not
# permitted`. Le déploiement doit poser l'un des deux, mesuré le 2026-08-27 :
#   Sysctl=net.ipv4.ping_group_range=1000 1000
#   AddCapability=NET_RAW
# Cela vit dans le quadlet, donc dans le rôle Ansible `ghostmon` d'apollo, pas
# ici. Les deux moitiés se corrigent ensemble ou ne corrigent rien.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY LICENSE NOTICE ./

# `static/` et `templates/` sont indispensables au DÉMARRAGE, pas seulement au
# rendu : `create_app()` monte `StaticFiles(directory=…)`, qui lève
# `RuntimeError: Directory '/app/static' does not exist` si le répertoire manque.
# L'application ne s'importe donc même pas.
#
# Le défaut n'était jamais apparu parce que l'image n'avait jamais été lancée —
# la CI la construisait puis la jetait. Un `podman build` qui réussit ne dit rien
# de ce que l'image fait au démarrage.
COPY static ./static
COPY templates ./templates

RUN pip install --upgrade pip && pip install -e ".[dev]"

RUN useradd --create-home --uid 1000 ghostmon \
    && chown -R ghostmon:ghostmon /app
USER ghostmon

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
