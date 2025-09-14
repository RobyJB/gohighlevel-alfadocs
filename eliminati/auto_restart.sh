#!/bin/bash

# ========================================
# SCRIPT DI AUTO-RESTART PER PRODUCTION
# ========================================
# Monitora il processo production e lo riavvia automaticamente in caso di crash

set -e

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configurazioni
PROJECT_NAME="alfadocs_production_monitor"
DEPLOY_SCRIPT="./deploy.sh"
MONITOR_LOG="./logs/auto_restart.log"
CHECK_INTERVAL=30  # Controlla ogni 30 secondi
MAX_RESTART_ATTEMPTS=5  # Massimo 5 tentativi consecutivi
RESTART_DELAY=10  # Attendi 10 secondi prima di riavviare

# Contatori
restart_count=0
last_restart_time=0

# Funzione per stampare messaggi colorati nel log
log_message() {
    local color=$1
    local message=$2
    local timestamp="[$(date '+%Y-%m-%d %H:%M:%S')]"
    echo -e "${color}${timestamp} ${message}${NC}" | tee -a "$MONITOR_LOG"
}

# Funzione per controllare se il processo production è in esecuzione
check_production_running() {
    # Controlla se ci sono container docker del progetto in esecuzione
    local running_containers=$(docker ps --filter "name=alfadocs" --format "{{.Names}}" | wc -l)
    
    # Controlla anche se ci sono processi deploy.sh production attivi
    local deploy_processes=$(pgrep -f "deploy.sh production" | wc -l)
    
    if [ "$running_containers" -gt 0 ] || [ "$deploy_processes" -gt 0 ]; then
        return 0  # Processo in esecuzione
    else
        return 1  # Processo non in esecuzione
    fi
}

# Funzione per avviare il processo production
start_production() {
    log_message $BLUE "🚀 Avvio processo production..."
    
    # Incrementa il contatore di restart
    restart_count=$((restart_count + 1))
    last_restart_time=$(date +%s)
    
    log_message $YELLOW "📊 Tentativo di restart #${restart_count}"
    
    # Avvia il processo in background
    nohup bash "$DEPLOY_SCRIPT" production >> "$MONITOR_LOG" 2>&1 &
    local pid=$!
    
    log_message $GREEN "✅ Processo production avviato con PID: $pid"
    
    # Attendi qualche secondo per verificare che si sia avviato correttamente
    sleep 5
    
    if kill -0 $pid 2>/dev/null; then
        log_message $GREEN "✅ Processo production confermato in esecuzione"
        return 0
    else
        log_message $RED "❌ Processo production non riuscito ad avviarsi"
        return 1
    fi
}

# Funzione per gestire il shutdown pulito
cleanup() {
    log_message $YELLOW "🔄 Ricevuto segnale di terminazione, fermando il monitoraggio..."
    
    # Ferma eventuali processi production in esecuzione
    pkill -f "deploy.sh production" || true
    docker-compose -f docker-compose.yml down || true
    
    log_message $GREEN "✅ Cleanup completato"
    exit 0
}

# Gestione segnali
trap cleanup SIGINT SIGTERM

# Funzione principale di monitoraggio
monitor_production() {
    log_message $GREEN "=========================================="
    log_message $GREEN "🔍 AVVIO MONITORAGGIO AUTO-RESTART"
    log_message $GREEN "=========================================="
    log_message $BLUE "📋 Configurazione:"
    log_message $BLUE "   - Controllo ogni: ${CHECK_INTERVAL} secondi"
    log_message $BLUE "   - Max restart consecutivi: ${MAX_RESTART_ATTEMPTS}"
    log_message $BLUE "   - Ritardo restart: ${RESTART_DELAY} secondi"
    log_message $BLUE "   - Log: ${MONITOR_LOG}"
    
    # Avvia il processo production se non è già in esecuzione
    if ! check_production_running; then
        log_message $YELLOW "⚠️ Processo production non in esecuzione, avvio..."
        if ! start_production; then
            log_message $RED "❌ Impossibile avviare il processo production"
            exit 1
        fi
    else
        log_message $GREEN "✅ Processo production già in esecuzione"
    fi
    
    # Loop di monitoraggio
    while true; do
        sleep $CHECK_INTERVAL
        
        # Verifica se il processo è ancora in esecuzione
        if check_production_running; then
            # Reset del contatore se il processo è stabile per più di 5 minuti
            current_time=$(date +%s)
            if [ $((current_time - last_restart_time)) -gt 300 ]; then
                if [ $restart_count -gt 0 ]; then
                    log_message $GREEN "✅ Processo stabile per 5+ minuti, reset contatore restart"
                    restart_count=0
                fi
            fi
            
            log_message $GREEN "✅ Processo production in esecuzione"
        else
            log_message $RED "❌ Processo production si è fermato!"
            
            # Controlla se abbiamo superato il limite di restart
            if [ $restart_count -ge $MAX_RESTART_ATTEMPTS ]; then
                log_message $RED "❌ Superato limite di restart ($MAX_RESTART_ATTEMPTS). Fermando il monitoraggio."
                log_message $RED "❌ Intervento manuale richiesto!"
                exit 1
            fi
            
            log_message $YELLOW "⏱️ Attendo ${RESTART_DELAY} secondi prima del restart..."
            sleep $RESTART_DELAY
            
            # Tenta il restart
            if start_production; then
                log_message $GREEN "✅ Restart completato con successo"
            else
                log_message $RED "❌ Restart fallito"
            fi
        fi
    done
}

# Crea directory per i log se non esiste
mkdir -p ./logs

# Verifica che il deploy.sh esista
if [ ! -f "$DEPLOY_SCRIPT" ]; then
    echo "❌ File $DEPLOY_SCRIPT non trovato!"
    exit 1
fi

# Avvia il monitoraggio
monitor_production 