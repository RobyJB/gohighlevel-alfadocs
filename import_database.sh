#!/bin/bash

# Script per importare un database PostgreSQL esportato
# Usa il file SQL creato da export_database.sh

if [ $# -eq 0 ]; then
    echo "Uso: $0 <file_esportazione.sql>"
    echo ""
    echo "Esempio:"
    echo "  $0 database_export_alfadocs_sync_20241205_143022.sql"
    exit 1
fi

EXPORT_FILE="$1"

# Verifica che il file esista
if [ ! -f "$EXPORT_FILE" ]; then
    echo "❌ File non trovato: $EXPORT_FILE"
    exit 1
fi

echo "=== Importazione Database PostgreSQL ==="
echo "File: $EXPORT_FILE"
echo ""

# Parametri di connessione per il nuovo server
echo "Configurazione del nuovo server:"
echo -n "Host del nuovo server: "
read NEW_DB_HOST
echo -n "Porta (default 5432): "
read NEW_DB_PORT
NEW_DB_PORT=${NEW_DB_PORT:-5432}
echo -n "Utente PostgreSQL: "
read NEW_DB_USER
echo -n "Nome del nuovo database: "
read NEW_DB_NAME

echo ""
echo -n "Password per l'utente $NEW_DB_USER: "
read -s NEW_DB_PASSWORD
echo ""

echo ""
echo "⚠️  ATTENZIONE: Questo processo creerà il database '$NEW_DB_NAME' se non esiste"
echo "   e sovrascriverà eventuali dati esistenti!"
echo ""
echo -n "Sei sicuro di voler continuare? (s/N): "
read CONFIRM

if [ "$CONFIRM" != "s" ] && [ "$CONFIRM" != "S" ]; then
    echo "Operazione annullata."
    exit 0
fi

echo ""
echo "Inizio importazione..."

# Imposta la password come variabile d'ambiente
export PGPASSWORD="$NEW_DB_PASSWORD"

# Importa il database
psql \
    --host="$NEW_DB_HOST" \
    --port="$NEW_DB_PORT" \
    --username="$NEW_DB_USER" \
    --dbname="postgres" \
    --file="$EXPORT_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Importazione completata con successo!"
    echo "🎉 Il database '$NEW_DB_NAME' è stato creato sul nuovo server"
    echo ""
    echo "📋 Prossimi passi:"
    echo "   1. Aggiorna le variabili d'ambiente nel nuovo server"
    echo "   2. Testa la connessione al database"
    echo "   3. Verifica che l'applicazione funzioni correttamente"
else
    echo ""
    echo "❌ Errore durante l'importazione!"
    echo "Controlla i log sopra per i dettagli dell'errore."
    exit 1
fi

# Rimuovi la password dalla memoria
unset PGPASSWORD
