# Usa Python 3.12 come immagine base
FROM python:3.12-slim

# Imposta le variabili d'ambiente per Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Crea l'utente per l'applicazione (sicurezza)
RUN useradd --create-home --shell /bin/bash alfadocs

# Aggiorna il sistema e installa le dipendenze di sistema
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Imposta la directory di lavoro
WORKDIR /app

# Copia il file requirements.txt prima per ottimizzare la cache Docker
COPY requirements.txt .

# Installa le dipendenze Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia tutti i file dell'applicazione
COPY . .

# I file Python non hanno bisogno di essere eseguibili (vengono chiamati con python3)

# Crea le directory per i log e imposta i permessi
RUN mkdir -p /app/logs && \
    touch /app/logs/alfadocs_careplan_sync.log && \
    chown -R alfadocs:alfadocs /app/logs && \
    chmod 666 /app/logs/alfadocs_careplan_sync.log

# Passa all'utente non root
USER alfadocs

# Comando di default (può essere sovrascritto)
CMD ["python3", "alfadocs_careplan_sync.py"]

# Metadata dell'immagine
LABEL maintainer="AlfaDocs Squad"
LABEL description="Servizio di sincronizzazione care plan codes da AlfaDocs"
LABEL version="1.0" 