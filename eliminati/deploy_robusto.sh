#!/bin/bash

# ========================================
# SCRIPT DI DEPLOY ALFADOCS SUPER ROBUSTO 
# ========================================
# Script DEFINITIVO per ambiente server - NON SI FERMA MAI!

set -e  # Ferma lo script se c'è un errore CRITICO (ma gestiamo tutto)

# Colori per l'output
RED='\033[0;31m'     
GREEN='\033[0;32m'   
YELLOW='\033[1;33m'  
BLUE='\033[0;34m'    
NC='\033[0m'         

# Configurazioni di base del progetto
PROJECT_NAME="alfadocs_squadd"
COMPOSE_FILE="docker-compose.yml"
LOG_DIR="./logs"

# LOG FILES DEDICATI
MAIN_LOG="./logs/deploy_main.log"
ERROR_LOG="./logs/deploy_errors.log"
DOCKER_LOG="./logs/docker_debug.log"
SYSTEM_LOG="./logs/system_status.log"

# Funzione di logging ROBUSTA che scrive SEMPRE
robust_log() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Scrivo SEMPRE, anche se fallisce qualcosa
    {
        echo "[$timestamp] [$level] $message" >> "$MAIN_LOG" 2>/dev/null || true
        echo "[$timestamp] [$level] $message" >&2 || true
        
        if [ "$level" = "ERROR" ]; then
            echo "[$timestamp] $message" >> "$ERROR_LOG" 2>/dev/null || true
        fi
    }
}

# Funzione per stampare messaggi colorati con logging
print_and_log() {
    local color=$1
    local level=$2
    local message=$3
    echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] ${message}${NC}"
    robust_log "$level" "$message"
}

# Funzione di inizializzazione sistema di log
init_logging() {
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    touch "$MAIN_LOG" "$ERROR_LOG" "$DOCKER_LOG" "$SYSTEM_LOG" 2>/dev/null || true
    
    robust_log "SYSTEM" "=========================================="
    robust_log "SYSTEM" "AVVIO SISTEMA ALFADOCS DEPLOY SUPER ROBUSTO"
    robust_log "SYSTEM" "=========================================="
}

# Funzione per verificare Docker con retry
check_docker_robust() {
    local max_attempts=5
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        print_and_log $BLUE "INFO" "Verifica Docker (tentativo $attempt/$max_attempts)..."
        
        if timeout 30 docker info > /dev/null 2>&1; then
            print_and_log $GREEN "SUCCESS" "Docker attivo e funzionante"
            return 0
        fi
        
        print_and_log $YELLOW "WARNING" "Docker non risponde, attendo e riprovo..."
        sleep $((attempt * 5))
        attempt=$((attempt + 1))
    done
    
    print_and_log $RED "ERROR" "Docker non disponibile dopo $max_attempts tentativi"
    return 1
}

# Funzione di pulizia SUPER AGGRESSIVA
nuclear_cleanup() {
    print_and_log $BLUE "INFO" "🧹 PULIZIA NUCLEARE - Elimino TUTTO quello correlato ad alfadocs..."
    
    # 1. Ferma TUTTI i processi alfadocs
    pkill -f "alfadocs" 2>/dev/null || true
    pkill -f "deploy_robusto" 2>/dev/null || true
    sleep 2
    pkill -9 -f "alfadocs" 2>/dev/null || true
    pkill -9 -f "deploy_robusto" 2>/dev/null || true
    
    # 2. Ferma e rimuovi container Docker
    {
        # Ferma tutti i container alfadocs
        docker ps -q --filter "name=alfadocs" | xargs -r docker stop 2>/dev/null || true
        docker ps -aq --filter "name=alfadocs" | xargs -r docker rm -f 2>/dev/null || true
        
        # Pulizia con docker-compose
        timeout 60 docker-compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
        
        # Rimuovi immagini del progetto
        docker images --filter "reference=${PROJECT_NAME}*" -q | xargs -r docker rmi -f 2>/dev/null || true
        
        # Pulizia generale
        docker system prune -f 2>/dev/null || true
        
    } >> "$DOCKER_LOG" 2>&1
    
    print_and_log $GREEN "SUCCESS" "Pulizia nucleare completata"
}

# Funzione per build Docker ROBUSTA con retry
docker_build_robust() {
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        print_and_log $BLUE "INFO" "Build Docker (tentativo $attempt/$max_attempts)..."
        
        {
            if timeout 600 docker-compose -f "$COMPOSE_FILE" build --no-cache; then
                print_and_log $GREEN "SUCCESS" "Build Docker completata"
                return 0
            fi
        } >> "$DOCKER_LOG" 2>&1
        
        print_and_log $YELLOW "WARNING" "Build fallita, pulizia e retry..."
        nuclear_cleanup
        sleep $((attempt * 10))
        attempt=$((attempt + 1))
    done
    
    print_and_log $RED "ERROR" "Build Docker fallita dopo $max_attempts tentativi"
    return 1
}

# Funzione per eseguire sincronizzazione con gestione errori ROBUSTA
run_sync_robust() {
    local sync_type=$1
    local script_name=$2
    local max_attempts=3
    local attempt=1
    
    # Determina il servizio Docker corretto in base al tipo di sincronizzazione
    local docker_service
    case "$script_name" in
        "alfadocs_patients_sync.py")
            docker_service="alfadocs-patients-sync"
            ;;
        "alfadocs_careplan_sync.py")
            docker_service="alfadocs-careplan-sync"
            ;;
        "ghl_sync.py")
            docker_service="alfadocs-careplan-sync"  # GHL usa il servizio careplan
            ;;
        *)
            docker_service="alfadocs-careplan-sync"  # Default
            ;;
    esac
    
    while [ $attempt -le $max_attempts ]; do
        print_and_log $BLUE "INFO" "🔄 $sync_type (tentativo $attempt/$max_attempts) usando servizio: $docker_service..."
        
        # Disabilita exit su errore per gestire manualmente
        set +e
        
        local start_time=$(date +%s)
        timeout 1800 docker-compose -f "$COMPOSE_FILE" run --rm "$docker_service" python3 "$script_name"
        local exit_code=$?
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        
        # Riabilita exit su errore
        set -e
        
        if [ $exit_code -eq 0 ]; then
            print_and_log $GREEN "SUCCESS" "✅ $sync_type completata in ${duration}s"
            return 0
        elif [ $exit_code -eq 124 ]; then
            print_and_log $RED "ERROR" "❌ $sync_type - TIMEOUT dopo 30 minuti"
        else
            print_and_log $RED "ERROR" "❌ $sync_type - Errore exit_code: $exit_code"
        fi
        
        # Solo su errore, faccio cleanup e retry
        if [ $attempt -lt $max_attempts ]; then
            print_and_log $YELLOW "WARNING" "Cleanup e retry in ${attempt}0 secondi..."
            nuclear_cleanup
            sleep $((attempt * 10))
        fi
        
        attempt=$((attempt + 1))
    done
    
    print_and_log $RED "ERROR" "$sync_type FALLITA dopo $max_attempts tentativi"
    return 1
}

# Funzione di monitoraggio sistema
monitor_system() {
    {
        echo "=== SYSTEM STATUS $(date) ==="
        echo "DOCKER STATUS:"
        docker system df 2>/dev/null || echo "Docker not available"
        echo ""
        echo "CONTAINERS:"
        docker ps -a --filter "name=alfadocs" 2>/dev/null || echo "No containers"
        echo ""
        echo "PROCESSES:"
        ps aux | grep -E "(deploy|alfadocs)" | grep -v grep || echo "No processes"
        echo ""
        echo "DISK SPACE:"
        df -h /var/lib/docker 2>/dev/null || echo "Cannot check docker disk"
        echo "==========================="
    } >> "$SYSTEM_LOG"
}

# MODALITÀ PRODUCTION SUPER ROBUSTA
production_mode_robust() {
    print_and_log $GREEN "INFO" "🏭 AVVIO MODALITÀ PRODUCTION SUPER ROBUSTA"
    print_and_log $GREEN "INFO" "💪 Questo script NON SI FERMA MAI - Progettato per server!"
    
    # Gestione segnali ROBUSTA
    cleanup_on_exit() {
        print_and_log $YELLOW "WARNING" "⚠️ Ricevuto segnale di terminazione - Shutdown controllato"
        nuclear_cleanup
        robust_log "SYSTEM" "Sistema fermato dall'utente"
        exit 0
    }
    
    # Ignoro SIGHUP (chiusura terminale) - CONTINUA SEMPRE
    trap '' SIGHUP
    trap cleanup_on_exit SIGINT SIGTERM
    
    # Variabili per il loop
    local cycle_count=1
    local total_errors=0
    local last_success_time=$(date +%s)
    
    # LOOP INFINITO ROBUSTO
    while true; do
        local loop_start_time=$(date +%s)
        robust_log "CYCLE" "========== CICLO #$cycle_count INIZIO =========="
        
        # Monitoraggio sistema
        monitor_system
        
        # Verifica Docker prima di tutto
        if ! check_docker_robust; then
            print_and_log $RED "ERROR" "Docker non disponibile, attendo 60s e riprovo..."
            total_errors=$((total_errors + 1))
            sleep 60
            continue
        fi
        
        # Pulizia preventiva ogni 10 cicli
        if [ $((cycle_count % 10)) -eq 0 ]; then
            print_and_log $BLUE "INFO" "Pulizia preventiva programmata (ciclo #$cycle_count)"
            nuclear_cleanup
        fi
        
        # Ricostruzione immagini se necessario
        if ! docker images | grep -q "${PROJECT_NAME}"; then
            print_and_log $YELLOW "WARNING" "Immagini mancanti, ricostruzione..."
            if ! docker_build_robust; then
                print_and_log $RED "ERROR" "Build fallita, salto questo ciclo"
                total_errors=$((total_errors + 1))
                sleep 60
                cycle_count=$((cycle_count + 1))
                continue
            fi
        fi
        
        # === SINCRONIZZAZIONE PAZIENTI (solo primo ciclo) ===
        if [ $cycle_count -eq 1 ]; then
            if run_sync_robust "Sincronizzazione Pazienti" "alfadocs_patients_sync.py"; then
                last_success_time=$(date +%s)
            else
                total_errors=$((total_errors + 1))
            fi
        fi
        
        # === SINCRONIZZAZIONE CAREPLAN ===
        if run_sync_robust "Sincronizzazione Careplan" "alfadocs_careplan_sync.py"; then
            last_success_time=$(date +%s)
        else
            total_errors=$((total_errors + 1))
        fi
        
        # === SINCRONIZZAZIONE GHL ===
        if run_sync_robust "Sincronizzazione GHL" "ghl_sync.py"; then
            last_success_time=$(date +%s)
        else
            total_errors=$((total_errors + 1))
        fi
        
        # Statistiche ciclo
        local loop_end_time=$(date +%s)
        local cycle_duration=$((loop_end_time - loop_start_time))
        local time_since_success=$((loop_end_time - last_success_time))
        
        robust_log "CYCLE" "Ciclo #$cycle_count completato in ${cycle_duration}s (errori totali: $total_errors)"
        
        # Allarme se troppi errori consecutivi
        if [ $time_since_success -gt 3600 ]; then  # 1 ora senza successi
            print_and_log $RED "ALARM" "🚨 ALLARME: Nessun successo da ${time_since_success}s!"
        fi
        
        # Pausa tra cicli
        print_and_log $BLUE "INFO" "⏸️ Pausa 30s prima del prossimo ciclo..."
        sleep 30
        
        cycle_count=$((cycle_count + 1))
    done
}

# Funzione per mostrare lo stato
show_status_robust() {
    print_and_log $BLUE "INFO" "📊 STATO SISTEMA ALFADOCS"
    
    echo -e "${BLUE}=== PROCESSI DEPLOY ===${NC}"
    ps aux | grep -E "(deploy_robusto)" | grep -v grep || echo "Nessun processo deploy attivo"
    
    echo -e "${BLUE}=== CONTAINER DOCKER ===${NC}"
    docker ps -a --filter "name=alfadocs" --format "table {{.Names}}\t{{.Status}}\t{{.CreatedAt}}" 2>/dev/null || echo "Nessun container alfadocs"
    
    echo -e "${BLUE}=== STATISTICHE LOG ===${NC}"
    if [ -f "$MAIN_LOG" ]; then
        echo "Log principale: $(wc -l < "$MAIN_LOG") righe"
        echo "Ultimi eventi:"
        tail -5 "$MAIN_LOG" 2>/dev/null || echo "Log non leggibile"
    fi
    
    if [ -f "$ERROR_LOG" ]; then
        local error_count=$(wc -l < "$ERROR_LOG" 2>/dev/null || echo "0")
        echo "Errori totali: $error_count"
    fi
}

# Funzione per fermare TUTTO
stop_all_robust() {
    print_and_log $YELLOW "WARNING" "⏹️ FERMATA TOTALE DEL SISTEMA"
    nuclear_cleanup
    print_and_log $GREEN "SUCCESS" "✅ Sistema completamente fermato"
}

# Funzione principale ROBUSTA
main() {
    local command=${1:-help}
    
    # Inizializzazione logging sempre
    init_logging
    
    case "$command" in
        "production")
            production_mode_robust
            ;;
        "status")
            show_status_robust
            ;;
        "stop")
            stop_all_robust
            ;;
        "cleanup")
            nuclear_cleanup
            ;;
        "test")
            check_docker_robust
            ;;
        *)
            echo -e "${GREEN}============================================${NC}"
            echo -e "${GREEN}    ALFADOCS DEPLOY SUPER ROBUSTO         ${NC}"
            echo -e "${GREEN}============================================${NC}"
            echo ""
            echo -e "${BLUE}Comandi disponibili:${NC}"
            echo "  ${GREEN}production${NC}  - Modalità production super robusta (NON SI FERMA MAI)"
            echo "  ${GREEN}status${NC}      - Mostra stato dettagliato del sistema"
            echo "  ${GREEN}stop${NC}        - Ferma completamente tutto"
            echo "  ${GREEN}cleanup${NC}     - Pulizia nucleare completa"
            echo "  ${GREEN}test${NC}        - Test connessione Docker"
            echo ""
            echo -e "${YELLOW}Per ambiente server:${NC}"
            echo "  $0 production  # Avvia e DIMENTICATELO - continua sempre!"
            echo ""
            ;;
    esac
}

# AVVIO PRINCIPALE
echo -e "${GREEN}"
echo "================================================"
echo "    ALFADOCS DEPLOY SUPER ROBUSTO              "
echo "    🚀 PROGETTATO PER AMBIENTE SERVER 🚀       "
echo "================================================"
echo -e "${NC}"

main "$@"