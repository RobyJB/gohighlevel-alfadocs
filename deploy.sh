#!/bin/bash
# Script di deploy semplificato: solo comando 'production'
# Pulisce container e immagini, builda e avvia i servizi in sequenza

set -e  # Esce al primo errore
# Ignora SIGHUP e SIGTERM in modo che lo script continui anche se si chiude il terminale o VSCode
trap '' SIGHUP SIGTERM

# Colori per output
BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# File docker-compose
COMPOSE_FILE="docker-compose.yml"

# Rileva automaticamente il comando Docker Compose disponibile
# Preferisce 'docker-compose' (v1); se non presente, usa 'docker compose' (v2)
if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

# Prepara directory e file di log con permessi scrivibili dal container non-root
prepare_logs_dir() {
    mkdir -p logs
    touch logs/alfadocs_patients_sync.log \
          logs/alfadocs_careplan_sync.log \
          logs/ghl_sync.log \
          logs/ghl_sync_errors.log \
          logs/alfadocs_sync_loop.log \
          logs/services_startup.log
    chmod 666 logs/alfadocs_patients_sync.log \
              logs/alfadocs_careplan_sync.log \
              logs/ghl_sync.log \
              logs/ghl_sync_errors.log \
              logs/alfadocs_sync_loop.log \
              logs/services_startup.log || true
}

# Funzione per loggare nel file centralizzato
log_deploy_action() {
    local action="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local pid=$$
    
    # Crea la directory se non esiste
    mkdir -p logs
    
    echo "${timestamp} - 🔄 DEPLOY ACTION: ${action} (PID: ${pid})" >> logs/services_startup.log
}

# Funzione di pulizia generale
cleanup() {
    echo -e "${BLUE}🔄 Pulizia generale...${NC}"
    # Ferma e rimuove i container e volumi orfani
    $COMPOSE_CMD -f "$COMPOSE_FILE" down --volumes --remove-orphans
    # Pulisce risorse Docker non utilizzate
    docker system prune -f
    # Rimuovo eventuali container one-off rimasti da 'docker-compose run'
    project=$(basename "$PWD")  # nome del progetto Docker-compose
    docker ps -q --filter "name=${project}-alfadocs-patients-sync-run" | xargs -r docker rm -f
    docker ps -q --filter "name=${project}-alfadocs-careplan-sync-run" | xargs -r docker rm -f
    docker ps -q --filter "name=${project}-alfadocs-ghl-sync-run"    | xargs -r docker rm -f
}

# Esegue una sola volta la sincronizzazione pazienti
single_patient_sync() {
    echo -e "${GREEN}🚀 Sincronizzazione pazienti (una volta)...${NC}"
    # Avvia il servizio alfadocs-patients-sync definito in docker-compose
    $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm alfadocs-patients-sync
}

# Loop infinito per sincronizzazione Careplan e GHL
loop_sync() {
    # File di log per il sync loop: tiene traccia di cicli e processi
    LOG_LOOP="./logs/alfadocs_sync_loop.log"
    # Inizializza il file di log con intestazione e timestamp
    echo "# $(date '+%Y-%m-%d %H:%M:%S') Avvio loop sincronizzazione Careplan e GHL" >> "$LOG_LOOP"
    # Contatore dei cicli
    cycle=1
    echo -e "${GREEN}🔁 Avvio loop sincronizzazione Careplan e GHL...${NC}"
    log_deploy_action "LOOP_START"
    while true; do
        # ===================================================================
        # Ciclo di sincronizzazione numero $cycle
        # ===================================================================
        log_deploy_action "CICLO_${cycle}_START"
        echo "# $(date '+%Y-%m-%d %H:%M:%S') [Ciclo $cycle] Inizio sincronizzazione Careplan" >> "$LOG_LOOP"
        echo -e "${BLUE}🔄 Sincronizzazione Careplan...${NC}"
        if ! $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm alfadocs-careplan-sync >> "$LOG_LOOP" 2>&1; then
            echo -e "${RED}⚠️ Errore sincronizzazione Careplan, continuo il loop...${NC}"
            echo "# $(date '+%Y-%m-%d %H:%M:%S') [Ciclo $cycle] Errore sincronizzazione Careplan" >> "$LOG_LOOP"
        fi
        echo "# $(date '+%Y-%m-%d %H:%M:%S') [Ciclo $cycle] Fine sincronizzazione Careplan" >> "$LOG_LOOP"

        echo -e "${BLUE}🔄 Sincronizzazione GHL...${NC}"
        echo "# $(date '+%Y-%m-%d %H:%M:%S') [Ciclo $cycle] Inizio sincronizzazione GHL" >> "$LOG_LOOP"
        if ! $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm alfadocs-ghl-sync >> "$LOG_LOOP" 2>&1; then
            echo -e "${RED}⚠️ Errore sincronizzazione GHL, continuo il loop...${NC}"
            echo "# $(date '+%Y-%m-%d %H:%M:%S') [Ciclo $cycle] Errore sincronizzazione GHL" >> "$LOG_LOOP"
        fi
        echo "# $(date '+%Y-%m-%d %H:%M:%S') [Ciclo $cycle] Fine sincronizzazione GHL" >> "$LOG_LOOP"

        echo -e "${BLUE}⏳ Attesa 30s prima del prossimo ciclo...${NC}"
        echo "# $(date '+%Y-%m-%d %H:%M:%S') [Ciclo $cycle] Attesa 30s prima del prossimo ciclo" >> "$LOG_LOOP"
        sleep 30
        # Incrementa il contatore per il ciclo successivo
        cycle=$((cycle+1))
    done
}

# Esegue un singolo ciclo di sincronizzazione Careplan e GHL
single_sync_cycle() {
    echo -e "${BLUE}🔄 Sincronizzazione Careplan...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm alfadocs-careplan-sync
    echo -e "${BLUE}🔄 Sincronizzazione GHL...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm alfadocs-ghl-sync
}

# Comando production: orchestrazione completa
production() {
    # 1) Pulizia
    cleanup
    # 2) Build Docker senza cache
    echo -e "${BLUE}🛠️ Build immagini Docker (no-cache)...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" build --no-cache
    # 2b) Prepara permessi log sul filesystem host
    prepare_logs_dir
    # 3) Sync pazienti una sola volta
    single_patient_sync
    # 4) Loop Careplan + GHL
    loop_sync
}

# Main: supporta solo 'production'
case "$1" in
    run_once)
        # Esegue pulizia, build, sync pazienti e un solo ciclo di careplan e ghl
        log_deploy_action "RUN_ONCE_START"
        cleanup
        echo -e "${BLUE}🛠️ Build immagini Docker (no-cache)...${NC}"
        $COMPOSE_CMD -f "$COMPOSE_FILE" build --no-cache
        # Prepara permessi log sul filesystem host
        prepare_logs_dir
        single_patient_sync
        echo -e "${GREEN}✅ Sync pazienti completata, eseguo un ciclo Careplan+GHL...${NC}"
        single_sync_cycle
        log_deploy_action "RUN_ONCE_END"
        ;;
    production)
        log_deploy_action "PRODUCTION_START"
        production
        ;;
    stop)
        log_deploy_action "STOP"
        echo -e "${BLUE}🛑 Fermando il servizio alfadocs-sync...${NC}"
        sudo systemctl stop alfadocs-sync
        echo -e "${GREEN}✅ Servizio fermato${NC}"
        ;;
    start)
        log_deploy_action "START"
        echo -e "${BLUE}🚀 Avviando il servizio alfadocs-sync...${NC}"
        sudo systemctl start alfadocs-sync
        echo -e "${GREEN}✅ Servizio avviato${NC}"
        ;;
    restart)
        log_deploy_action "RESTART"
        echo -e "${BLUE}🔄 Riavviando il servizio alfadocs-sync...${NC}"
        sudo systemctl restart alfadocs-sync
        echo -e "${GREEN}✅ Servizio riavviato${NC}"
        ;;
    status)
        echo -e "${BLUE}📊 Stato del servizio alfadocs-sync:${NC}"
        sudo systemctl status alfadocs-sync
        ;;
    logs)
        echo -e "${BLUE}📋 Log del servizio alfadocs-sync (Ctrl+C per uscire):${NC}"
        sudo journalctl -fu alfadocs-sync
        ;;
    loop-logs)
        echo -e "${BLUE}📋 Log del loop di sincronizzazione (Ctrl+C per uscire):${NC}"
        tail -f logs/alfadocs_sync_loop.log
        ;;
    startup-logs)
        echo -e "${BLUE}📋 Log centralizzato avvio servizi (Ctrl+C per uscire):${NC}"
        tail -f logs/services_startup.log
        ;;
    *)
        echo -e "${RED}Uso: $0 {production|stop|start|restart|status|logs|loop-logs|startup-logs}${NC}"
        echo -e "${BLUE}Comandi disponibili:${NC}"
        echo -e "  production    - Esegue deploy completo (pulizia + build + sync)"
        echo -e "  stop          - Ferma il servizio"
        echo -e "  start         - Avvia il servizio"
        echo -e "  restart       - Riavvia il servizio"
        echo -e "  status        - Mostra stato del servizio"
        echo -e "  logs          - Mostra log systemd in tempo reale"
        echo -e "  loop-logs     - Mostra log del loop di sincronizzazione"
        echo -e "  startup-logs  - Mostra log centralizzato avvio servizi"
        exit 1
        ;;
esac 