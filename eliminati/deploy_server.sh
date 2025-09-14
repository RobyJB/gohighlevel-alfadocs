#!/bin/bash

# ================================================
# ALFADOCS DEPLOY PER SERVER - NON SI FERMA MAI!
# ================================================

set +e  # NON fermare MAI lo script per errori

# Colori
RED='\033[0;31m'     
GREEN='\033[0;32m'   
YELLOW='\033[1;33m'  
BLUE='\033[0;34m'    
NC='\033[0m'

# Configurazioni
PROJECT_NAME="alfadocs_squadd"
COMPOSE_FILE="docker-compose.yml"

# File di log ROBUSTI
mkdir -p ./logs 2>/dev/null || true
MAIN_LOG="./logs/server_main.log"
ERROR_LOG="./logs/server_errors.log"

# Funzione di log ROBUSTA che scrive SEMPRE
log_robust() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Scrivo su file
    echo "[$timestamp] [$level] $message" >> "$MAIN_LOG" 2>/dev/null || true
    
    # Scrivo su schermo
    echo -e "${GREEN}[$timestamp] $message${NC}"
    
    # Se errore, scrivo anche nel log errori
    if [ "$level" = "ERROR" ]; then
        echo "[$timestamp] $message" >> "$ERROR_LOG" 2>/dev/null || true
    fi
}

# Funzione di pulizia AGGRESSIVA
cleanup_total() {
    log_robust "INFO" "🧹 Pulizia totale container..."
    
    # Uccidi tutti i processi alfadocs
    pkill -f "alfadocs" 2>/dev/null || true
    sleep 2
    pkill -9 -f "alfadocs" 2>/dev/null || true
    
    # Ferma e rimuovi container
    docker ps -q --filter "name=alfadocs" | xargs -r docker stop 2>/dev/null || true
    docker ps -aq --filter "name=alfadocs" | xargs -r docker rm -f 2>/dev/null || true
    
    # Pulizia compose
    docker-compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
    
    # Rimuovi immagini vecchie
    docker images --filter "reference=${PROJECT_NAME}*" -q | xargs -r docker rmi -f 2>/dev/null || true
    
    log_robust "SUCCESS" "✅ Pulizia completata"
}

# Verifica Docker ROBUSTA
check_docker() {
    local attempts=0
    while [ $attempts -lt 10 ]; do
        if timeout 30 docker info >/dev/null 2>&1; then
            log_robust "SUCCESS" "✅ Docker OK"
            return 0
        fi
        log_robust "WARNING" "⚠️ Docker non risponde, riprovo..."
        sleep 10
        attempts=$((attempts + 1))
    done
    log_robust "ERROR" "❌ Docker non disponibile"
    return 1
}

# Build ROBUSTA con retry
build_robust() {
    local attempts=0
    while [ $attempts -lt 5 ]; do
        log_robust "INFO" "🔨 Build Docker (tentativo $((attempts + 1)))"
        
        if timeout 900 docker-compose -f "$COMPOSE_FILE" build --no-cache >/dev/null 2>&1; then
            log_robust "SUCCESS" "✅ Build completata"
            return 0
        fi
        
        log_robust "WARNING" "⚠️ Build fallita, pulizia e retry..."
        cleanup_total
        sleep 30
        attempts=$((attempts + 1))
    done
    
    log_robust "ERROR" "❌ Build fallita dopo 5 tentativi"
    return 1
}

# Esecuzione sincronizzazione ROBUSTA
run_sync() {
    local name=$1
    local script=$2
    local attempts=0
    
    while [ $attempts -lt 3 ]; do
        log_robust "INFO" "🔄 $name (tentativo $((attempts + 1)))"
        
        local start_time=$(date +%s)
        if timeout 1800 docker-compose -f "$COMPOSE_FILE" run --rm alfadocs-careplan-sync python3 "$script" >/dev/null 2>&1; then
            local end_time=$(date +%s)
            local duration=$((end_time - start_time))
            log_robust "SUCCESS" "✅ $name completata in ${duration}s"
            return 0
        fi
        
        log_robust "WARNING" "⚠️ $name fallita, retry..."
        cleanup_total
        sleep 20
        attempts=$((attempts + 1))
    done
    
    log_robust "ERROR" "❌ $name fallita dopo 3 tentativi"
    return 1
}

# MODALITÀ SERVER PRODUCTION
server_mode() {
    log_robust "SYSTEM" "🚀 AVVIO MODALITÀ SERVER - NON SI FERMA MAI!"
    
    # Ignora TUTTI i segnali tranne kill -9
    trap '' SIGHUP SIGINT SIGTERM
    
    local cycle=1
    local total_errors=0
    
    # LOOP INFINITO INDISTRUTTIBILE
    while true; do
        log_robust "CYCLE" "========== CICLO #$cycle =========="
        
        # Verifica Docker
        if ! check_docker; then
            log_robust "ERROR" "Docker non disponibile, attendo 60s..."
            total_errors=$((total_errors + 1))
            sleep 60
            continue
        fi
        
        # Pulizia ogni 10 cicli
        if [ $((cycle % 10)) -eq 0 ]; then
            cleanup_total
        fi
        
        # Build se necessario
        if ! docker images | grep -q "${PROJECT_NAME}" >/dev/null 2>&1; then
            if ! build_robust; then
                log_robust "ERROR" "Build fallita, salto ciclo"
                total_errors=$((total_errors + 1))
                sleep 60
                cycle=$((cycle + 1))
                continue
            fi
        fi
        
        # Sync pazienti (solo primo ciclo o ogni 50 cicli)
        if [ $cycle -eq 1 ] || [ $((cycle % 50)) -eq 0 ]; then
            run_sync "PAZIENTI" "alfadocs_patients_sync.py" || total_errors=$((total_errors + 1))
        fi
        
        # Sync careplan
        run_sync "CAREPLAN" "alfadocs_careplan_sync.py" || total_errors=$((total_errors + 1))
        
        # Sync GHL
        run_sync "GHL" "ghl_sync.py" || total_errors=$((total_errors + 1))
        
        log_robust "INFO" "📊 Ciclo #$cycle completato (errori totali: $total_errors)"
        
        # Pausa tra cicli
        sleep 30
        cycle=$((cycle + 1))
        
        # Reset errori ogni 100 cicli
        if [ $((cycle % 100)) -eq 0 ]; then
            total_errors=0
        fi
    done
}

# Stato sistema
show_status() {
    echo -e "${BLUE}=== STATO SISTEMA ALFADOCS ===${NC}"
    
    echo "PROCESSI:"
    ps aux | grep -E "(deploy_server|alfadocs)" | grep -v grep || echo "Nessun processo"
    
    echo ""
    echo "CONTAINER:"
    docker ps -a --filter "name=alfadocs" || echo "Nessun container"
    
    echo ""
    echo "LOG RECENTI:"
    if [ -f "$MAIN_LOG" ]; then
        tail -10 "$MAIN_LOG"
    else
        echo "Nessun log"
    fi
}

# Stop totale
stop_total() {
    log_robust "SYSTEM" "⏹️ STOP TOTALE RICHIESTO"
    
    # Uccidi tutti i processi deploy_server
    pkill -f "deploy_server" 2>/dev/null || true
    sleep 2
    pkill -9 -f "deploy_server" 2>/dev/null || true
    
    cleanup_total
    log_robust "SYSTEM" "✅ Sistema completamente fermato"
}

# MAIN
case "${1:-help}" in
    "server")
        server_mode
        ;;
    "status")
        show_status
        ;;
    "stop")
        stop_total
        ;;
    "cleanup")
        cleanup_total
        ;;
    *)
        echo -e "${GREEN}============================================${NC}"
        echo -e "${GREEN}   ALFADOCS DEPLOY PER SERVER              ${NC}"
        echo -e "${GREEN}============================================${NC}"
        echo ""
        echo -e "${BLUE}Comandi:${NC}"
        echo "  ${GREEN}server${NC}   - Modalità server (NON SI FERMA MAI)"
        echo "  ${GREEN}status${NC}   - Stato sistema"
        echo "  ${GREEN}stop${NC}     - Ferma tutto"
        echo "  ${GREEN}cleanup${NC}  - Pulizia totale"
        echo ""
        echo -e "${YELLOW}Per server:${NC} ./deploy_server.sh server"
        ;;
esac 