#!/bin/bash

# ========================================
# SCRIPT DI DEPLOY ALFADOCS CAREPLAN SYNC
# ========================================
# Automatizza il deployment con pulizia cache e gestione container

set -e  # Esci in caso di errore

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configurazioni
PROJECT_NAME="alfadocs_careplan_sync"
COMPOSE_FILE="docker-compose.yml"
LOG_DIR="./logs"

# Funzione per stampare messaggi colorati
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}[$(date '+%Y-%m-%d %H:%M:%S')] ${message}${NC}"
}

# Funzione per verificare se Docker è in esecuzione
check_docker() {
    print_message $BLUE "🔍 Verifico se Docker è in esecuzione..."
    if ! docker info > /dev/null 2>&1; then
        print_message $RED "❌ Docker non è in esecuzione. Avvia Docker e riprova."
        exit 1
    fi
    print_message $GREEN "✅ Docker è attivo"
}

# Funzione per verificare se il file .env esiste
check_env_file() {
    print_message $BLUE "🔍 Verifico file .env..."
    if [ ! -f ".env" ]; then
        print_message $RED "❌ File .env non trovato!"
        print_message $YELLOW "📝 Crea il file .env con le credenziali necessarie"
        exit 1
    fi
    print_message $GREEN "✅ File .env trovato"
}

# Funzione per verificare le porte in uso
check_ports() {
    print_message $BLUE "🔍 Verifico porte in uso..."
    
    # Estrai la porta dal file .env
    DB_PORT=$(grep "^DB_PORT=" .env | cut -d'=' -f2)
    
    if [ -n "$DB_PORT" ]; then
        if lsof -Pi :$DB_PORT -sTCP:LISTEN -t > /dev/null 2>&1; then
            print_message $YELLOW "⚠️ Porta $DB_PORT già in uso"
            print_message $BLUE "📋 Processi che usano la porta $DB_PORT:"
            lsof -Pi :$DB_PORT -sTCP:LISTEN
        else
            print_message $GREEN "✅ Porta $DB_PORT disponibile"
        fi
    fi
}

# Funzione per creare directory necessarie
create_directories() {
    print_message $BLUE "📁 Creo le directory necessarie..."
    mkdir -p $LOG_DIR
    
    # Creo il file di log solo se non esiste
    if [ ! -f "alfadocs_careplan_sync.log" ]; then
        touch alfadocs_careplan_sync.log
    fi
    
    # Provo a impostare i permessi, ma non esco se fallisce
    chmod 666 alfadocs_careplan_sync.log 2>/dev/null || print_message $YELLOW "⚠️ Non è stato possibile modificare i permessi del file di log. Il file potrebbe non essere scrivibile."
    
    print_message $GREEN "✅ Directory create"
}

# Funzione per pulizia cache e container
cleanup() {
    print_message $BLUE "🧹 Inizio pulizia specifica dei container alfadocs..."
    
    # Ferma e rimuove SOLO i container alfadocs (in esecuzione e fermati)
    print_message $YELLOW "⏹️ Fermando e rimuovendo SOLO i container alfadocs..."
    
    # Trova tutti i container alfadocs (in esecuzione e fermati)
    ALFADOCS_CONTAINERS=$(docker ps -aq --filter "name=alfadocs" 2>/dev/null || true)
    if [ ! -z "$ALFADOCS_CONTAINERS" ]; then
        print_message $YELLOW "🔍 Container alfadocs trovati: $ALFADOCS_CONTAINERS"
        # Ferma forzatamente tutti i container alfadocs
        docker stop $ALFADOCS_CONTAINERS 2>/dev/null || true
        # Rimuove forzatamente tutti i container alfadocs
        docker rm -f $ALFADOCS_CONTAINERS 2>/dev/null || true
        print_message $GREEN "✅ Container alfadocs rimossi forzatamente"
    else
        print_message $GREEN "✅ Nessun container alfadocs da rimuovere"
    fi
    
    # Ferma e rimuove SOLO i container dal compose di questo progetto
    print_message $YELLOW "⏹️ Fermando container specifici da docker-compose..."
    docker-compose -f $COMPOSE_FILE down --remove-orphans 2>/dev/null || true
    
    # Rimuove SOLO le immagini specifiche del progetto alfadocs
    print_message $YELLOW "🗑️ Rimuovo SOLO le immagini alfadocs_squadd..."
    ALFADOCS_IMAGES=$(docker images --filter "reference=alfadocs_squadd*" -q 2>/dev/null || true)
    if [ ! -z "$ALFADOCS_IMAGES" ]; then
        docker rmi -f $ALFADOCS_IMAGES 2>/dev/null || true
        print_message $GREEN "✅ Immagini alfadocs_squadd rimosse"
    fi
    
    # Rimuove SOLO le immagini senza tag create da questo progetto
    print_message $YELLOW "🗑️ Rimuovo solo immagini dangling di questo progetto..."
    docker image prune -f 2>/dev/null || true
    
    # Verifica finale
    print_message $BLUE "🔍 Verifica finale - container alfadocs rimasti:"
    REMAINING_CONTAINERS=$(docker ps -a --filter "name=alfadocs" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || true)
    if [ ! -z "$REMAINING_CONTAINERS" ]; then
        print_message $YELLOW "⚠️ Container alfadocs ancora presenti:"
        echo "$REMAINING_CONTAINERS"
    else
        print_message $GREEN "✅ Nessun container alfadocs rimanente"
    fi
    
    print_message $GREEN "✅ Pulizia specifica completata (altri progetti Docker NON toccati)"
}

# Funzione per build e deploy
deploy() {
    print_message $BLUE "🚀 Inizio build e deploy..."
    
    # Se siamo in modalità only_patients, disabilita il careplan sync
    if [ "$1" = "only_patients" ]; then
        export CAREPLAN_RESTART="no"
        export CAREPLAN_COMMAND="tail -f /dev/null"
        export PATIENTS_COMMAND="python3 alfadocs_patients_sync.py"
    else
        export CAREPLAN_RESTART="unless-stopped"
        export CAREPLAN_COMMAND="python3 alfadocs_careplan_sync.py"
        export PATIENTS_COMMAND="tail -f /dev/null"
    fi
    
    # Build delle immagini
    print_message $YELLOW "🔨 Build delle immagini Docker..."
    docker-compose -f $COMPOSE_FILE build --no-cache
    
    # Avvio dei servizi
    print_message $YELLOW "▶️ Avvio dei servizi..."
    docker-compose -f $COMPOSE_FILE up -d
    
    print_message $GREEN "✅ Deploy completato"
}

# Funzione per monitoraggio
monitor() {
    print_message $BLUE "📊 Stato dei container:"
    docker-compose -f $COMPOSE_FILE ps
    
    print_message $BLUE "📊 Utilizzo risorse:"
    docker stats --no-stream
    
    print_message $BLUE "📋 Ultimi log (ultime 20 righe):"
    docker-compose -f $COMPOSE_FILE logs --tail=20
}

# Funzione per visualizzare i log in tempo reale
logs() {
    print_message $BLUE "📋 Visualizzazione log in tempo reale (CTRL+C per uscire)..."
    docker-compose -f $COMPOSE_FILE logs -f
}

# Funzione per stop
stop() {
    print_message $YELLOW "⏹️ Fermando i servizi..."
    docker-compose -f $COMPOSE_FILE down
    print_message $GREEN "✅ Servizi fermati"
}

# Funzione per restart
restart() {
    print_message $BLUE "🔄 Riavvio dei servizi..."
    stop
    sleep 2
    docker-compose -f $COMPOSE_FILE up -d
    print_message $GREEN "✅ Servizi riavviati"
}

# Funzione per eseguire il sync manualmente
run_sync() {
    print_message $BLUE "🔄 Eseguo sincronizzazione manuale..."
    docker-compose -f $COMPOSE_FILE exec alfadocs-careplan-sync python3 alfadocs_careplan_sync.py
}

# Funzione per eseguire il sync pazienti manualmente
run_patients_sync() {
    print_message $BLUE "🔄 Eseguo sincronizzazione pazienti manuale..."
    # Ferma il container se è in esecuzione
    docker-compose -f $COMPOSE_FILE stop alfadocs-patients-sync
    # Riavvia con il comando corretto
    export PATIENTS_COMMAND="python3 alfadocs_patients_sync.py"
    docker-compose -f $COMPOSE_FILE up -d alfadocs-patients-sync
    # Attendi il completamento
    docker-compose -f $COMPOSE_FILE logs -f alfadocs-patients-sync
}

# Funzione per eseguire il sync GHL manualmente
run_ghl_sync() {
    print_message $BLUE "🔄 Eseguo sincronizzazione GHL manuale..."
    docker-compose -f $COMPOSE_FILE run --rm alfadocs-careplan-sync python3 ghl_sync.py
}

# Funzione per debug/shell access
debug() {
    print_message $BLUE "🐛 Accesso shell per debug..."
    docker-compose -f $COMPOSE_FILE exec alfadocs-careplan-sync /bin/bash
}

# Funzione per test delle credenziali
test_credentials() {
    print_message $BLUE "🔐 Test credenziali..."
    docker-compose -f $COMPOSE_FILE run --rm alfadocs-careplan-sync python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()

# Test database
try:
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
    print('✅ Database: Connessione riuscita')
    conn.close()
except Exception as e:
    print(f'❌ Database: {e}')

# Test API AlfaDocs
try:
    import requests
    headers = {'X-Api-Key': os.getenv('ALFADOCS_API_KEY')}
    response = requests.get(f\"{os.getenv('ALFADOCS_BASE_URL')}/v1/practices/{os.getenv('ALFADOCS_PRACTICE_ID')}/archives/{os.getenv('ALFADOCS_ARCHIVE_ID')}/appointments\", headers=headers, timeout=10, params={'limit': 1})
    if response.status_code == 200:
        print('✅ AlfaDocs API: Credenziali valide')
    else:
        print(f'❌ AlfaDocs API: HTTP {response.status_code}')
except Exception as e:
    print(f'❌ AlfaDocs API: {e}')
"
}

# Funzione di help
show_help() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}    ALFADOCS CAREPLAN SYNC DEPLOY     ${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo -e "${BLUE}Uso: $0 [comando]${NC}"
    echo ""
    echo -e "${YELLOW}Comandi disponibili:${NC}"
    echo "  deploy        - Deploy completo (cleanup + build + start)"
    echo "  only_patients - Deploy completo ma avvia solo sync pazienti"
    echo "  production    - Modalità production (pazienti una volta, poi loop careplan+ghl)"
    echo "  auto-restart  - Modalità production con auto-restart in caso di crash"
    echo "  start         - Avvia i servizi"
    echo "  stop          - Ferma i servizi"
    echo "  restart       - Riavvia i servizi"
    echo "  cleanup       - Pulizia cache e container"
    echo "  monitor       - Mostra stato container e log"
    echo "  logs          - Visualizza log in tempo reale"
    echo "  sync          - Esegue sincronizzazione manuale"
    echo "  ghl_sync      - Esegue sincronizzazione GHL manuale"
    echo "  debug         - Accesso shell per debug"
    echo "  test          - Test credenziali"
    echo "  help          - Mostra questo help"
    echo ""
    echo -e "${YELLOW}Esempi:${NC}"
    echo "  $0 deploy          # Deploy completo"
    echo "  $0 production      # Modalità production continua"
    echo "  $0 auto-restart    # Modalità production con auto-restart"
    echo "  $0 only_patients   # Deploy completo ma solo sync pazienti"
    echo "  $0 logs            # Visualizza log"
    echo "  $0 test            # Testa le credenziali"
}

# Funzione principale
main() {
    case "${1:-help}" in
        "deploy")
            check_docker
            check_env_file
            check_ports
            create_directories
            cleanup
            deploy "normal"
            monitor
            ;;
        "only_patients")
            check_docker
            check_env_file
            check_ports
            create_directories
            cleanup
            deploy "only_patients"
            monitor
            ;;
        "production")
            # Modalità production: sync pazienti una volta, poi loop continuo con auto-restart
            check_docker
            check_env_file
            check_ports
            create_directories
            
            # Setup file di log per modalità production
            PRODUCTION_LOG="./logs/production_sync.log"
            RESTART_LOG="./logs/auto_restart.log"
            mkdir -p ./logs
            
            # Configurazioni auto-restart
            RESTART_DELAY=10
            CHECK_INTERVAL=30
            restart_count=0
            last_restart_time=0
            cycle_count=1
            
            # Funzione per scrivere nel log di production
            log_production() {
                local message="$1"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] $message" | tee -a "$PRODUCTION_LOG"
            }
            
            # Funzione per log auto-restart
            log_restart() {
                local message="$1"
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] $message" | tee -a "$RESTART_LOG"
            }
            
            # Funzione per eseguire un ciclo di sincronizzazione con gestione errori
            run_sync_cycle() {
                local cycle_num=$1
                
                # Gestione errori con trap
                set +e  # Disabilita uscita automatica su errore
                
                log_production "----------------------------------------"
                log_production "🔄 CICLO #${cycle_num} - INIZIO Sincronizzazione careplan"
                print_message $BLUE "🔄 Ciclo #${cycle_num}: sincronizzazione careplan..."
                
                if docker-compose -f $COMPOSE_FILE run --rm alfadocs-careplan-sync python3 alfadocs_careplan_sync.py; then
                    log_production "✅ CICLO #${cycle_num} - COMPLETATO Sincronizzazione careplan"
                else
                    log_production "❌ CICLO #${cycle_num} - ERRORE Sincronizzazione careplan"
                    set -e
                    return 1
                fi
                
                log_production "🔄 CICLO #${cycle_num} - INIZIO Sincronizzazione GHL"
                print_message $BLUE "🔄 Ciclo #${cycle_num}: sincronizzazione GHL..."
                
                if docker-compose -f $COMPOSE_FILE run --rm alfadocs-careplan-sync python3 ghl_sync.py; then
                    log_production "✅ CICLO #${cycle_num} - COMPLETATO Sincronizzazione GHL"
                else
                    log_production "❌ CICLO #${cycle_num} - ERRORE Sincronizzazione GHL"
                    set -e
                    return 1
                fi
                
                log_production "✅ CICLO #${cycle_num} - COMPLETATO INTERAMENTE"
                print_message $GREEN "✅ Ciclo #${cycle_num} completato con successo"
                
                set -e  # Riabilita uscita automatica su errore
                return 0
            }
            
            # Funzione per inizializzazione completa
            initialize_production() {
                # Pulizia iniziale
                cleanup
                # Build delle immagini
                print_message $YELLOW "🔨 Build delle immagini Docker..."
                docker-compose -f $COMPOSE_FILE build --no-cache
                
                # Inizializzazione log di production
                log_production "=========================================="
                log_production "🚀 AVVIO MODALITÀ PRODUCTION CON AUTO-RESTART"
                log_production "=========================================="
                log_restart "🔍 Sistema auto-restart attivo (restart illimitati)"
                
                # Sincronizzazione pazienti iniziale (una sola volta)
                log_production "🔄 INIZIO - Sincronizzazione pazienti iniziale"
                print_message $BLUE "🔄 Sincronizzazione pazienti iniziale..."
                if ! docker-compose -f $COMPOSE_FILE run --rm alfadocs-patients-sync python3 alfadocs_patients_sync.py; then
                    log_production "❌ ERRORE - Sincronizzazione pazienti iniziale"
                    return 1
                fi
                log_production "✅ COMPLETATO - Sincronizzazione pazienti iniziale"
                
                # Sincronizzazione careplan iniziale
                log_production "🔄 INIZIO - Sincronizzazione careplan iniziale"
                print_message $BLUE "🔄 Sincronizzazione careplan iniziale..."
                if ! docker-compose -f $COMPOSE_FILE run --rm alfadocs-careplan-sync python3 alfadocs_careplan_sync.py; then
                    log_production "❌ ERRORE - Sincronizzazione careplan iniziale"
                    return 1
                fi
                log_production "✅ COMPLETATO - Sincronizzazione careplan iniziale"
                
                # Sincronizzazione GHL iniziale
                log_production "🔄 INIZIO - Sincronizzazione GHL iniziale"
                print_message $BLUE "🔄 Sincronizzazione GHL iniziale..."
                if ! docker-compose -f $COMPOSE_FILE run --rm alfadocs-careplan-sync python3 ghl_sync.py; then
                    log_production "❌ ERRORE - Sincronizzazione GHL iniziale"
                    return 1
                fi
                log_production "✅ COMPLETATO - Sincronizzazione GHL iniziale"
                
                return 0
            }
            
            # Gestione segnali per shutdown pulito
            cleanup_production() {
                log_restart "⚠️ Ricevuto segnale di terminazione"
                docker-compose -f $COMPOSE_FILE down || true
                exit 0
            }
            trap cleanup_production SIGINT SIGTERM
            
            # Loop principale con auto-restart
            while true; do
                # Inizializzazione
                if initialize_production; then
                    log_restart "✅ Inizializzazione completata con successo"
                    restart_count=0  # Reset del contatore al successo
                    last_restart_time=$(date +%s)
                else
                    log_restart "❌ Errore durante l'inizializzazione"
                    restart_count=$((restart_count + 1))
                    
                    log_restart "⏱️ Attendo ${RESTART_DELAY} secondi prima del restart #${restart_count}..."
                    sleep $RESTART_DELAY
                    continue
                fi
                
                # Loop continuo di sincronizzazione
                log_production "🔄 AVVIO LOOP CONTINUO di sincronizzazione"
                print_message $GREEN "🔄 Avvio loop continuo di sincronizzazione..."
                
                while true; do
                    # Esegui ciclo di sincronizzazione
                    if run_sync_cycle $cycle_count; then
                        cycle_count=$((cycle_count + 1))
                        
                        # Reset contatore restart se tutto va bene per 5+ minuti
                        current_time=$(date +%s)
                        if [ $((current_time - last_restart_time)) -gt 300 ] && [ $restart_count -gt 0 ]; then
                            log_restart "✅ Sistema stabile per 5+ minuti, reset contatore restart"
                            restart_count=0
                        fi
                    else
                        # Errore nel ciclo - riavvia tutto
                        log_restart "❌ Errore nel ciclo di sincronizzazione #${cycle_count}"
                        restart_count=$((restart_count + 1))
                        
                        log_restart "⏱️ Attendo ${RESTART_DELAY} secondi prima del restart completo #${restart_count}..."
                        sleep $RESTART_DELAY
                        break  # Esce dal loop interno per reinizializzare tutto
                    fi
                done
            done
            ;;
        "auto-restart")
            # Modalità auto-restart: avvia production con monitoraggio e auto-restart
            print_message $GREEN "🔄 Avvio modalità AUTO-RESTART"
            print_message $BLUE "📋 Questa modalità monitora il processo production e lo riavvia automaticamente in caso di crash"
            
            # Verifica che lo script auto_restart.sh esista
            if [ ! -f "./auto_restart.sh" ]; then
                print_message $RED "❌ Script auto_restart.sh non trovato!"
                exit 1
            fi
            
            # Avvia il monitoraggio
            exec ./auto_restart.sh
            ;;
        "start")
            check_docker
            check_env_file
            check_ports
            create_directories
            cleanup
            docker-compose -f $COMPOSE_FILE up -d
            monitor
            ;;
        "stop")
            stop
            ;;
        "restart")
            check_docker
            check_env_file
            check_ports
            create_directories
            cleanup
            restart
            monitor
            ;;
        "cleanup")
            cleanup
            ;;
        "monitor")
            monitor
            ;;
        "logs")
            logs
            ;;
        "sync")
            run_sync
            ;;
        "ghl_sync")
            check_docker
            check_env_file
            check_ports
            create_directories
            cleanup
            # Build dell'immagine per GHL Sync
            print_message $YELLOW "🔨 Build immagine GHL Sync..."
            docker-compose -f $COMPOSE_FILE build --no-cache alfadocs-careplan-sync
            # Eseguo sincronizzazione GHL
            run_ghl_sync
            ;;
        "debug")
            debug
            ;;
        "test")
            test_credentials
            ;;
        "help"|*)
            show_help
            ;;
    esac
}

# Header del script
echo -e "${GREEN}"
echo "=========================================="
echo "  ALFADOCS CAREPLAN SYNC DEPLOY SCRIPT   "
echo "=========================================="
echo -e "${NC}"

# Esegui la funzione principale
main "$@" 