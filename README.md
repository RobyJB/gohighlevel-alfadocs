# AlfaDocs Sync — Panoramica e Guida

Sistema che sincronizza dati tra AlfaDocs e GHL (Squadd) usando tre componenti separati. Qui trovi cosa fanno, come avviarli e dove vedere i log.

## 🔧 Componenti principali

- **alfadocs_careplan_sync.py**: prende gli appuntamenti da AlfaDocs e salva sul database locale. Se l'appuntamento ha un care plan, recupera il relativo codice (care_plan_code) e lo scrive nel record dell'appuntamento. Verifica che il paziente esista nel DB; se manca, lo inserisce automaticamente.

- **alfadocs_patients_sync.py**: importa/aggiorna tutti i pazienti da AlfaDocs nel DB. Pulisce i dati (telefono, CF, date), calcola un hash per capire se un paziente è cambiato e marca i record per la sincronizzazione con GHL.

- **ghl_sync.py**: legge dal DB i pazienti e gli appuntamenti da sincronizzare e li crea/aggiorna su GHL. Sceglie il calendario corretto in base al care_plan_code usando `config/calendars.json` e assegna l'operatore tramite `config/operators.json`. Gestisce anche aggiornamenti e cancellazioni.

## ✅ Requisiti

Assicurati di avere un file `.env` con le variabili necessarie (senza condividerne i valori):

- **Database**: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- **AlfaDocs**: `ALFADOCS_API_KEY`, `ALFADOCS_PRACTICE_ID`, `ALFADOCS_ARCHIVE_ID`, `ALFADOCS_BASE_URL`
- **GHL/Squadd**: `GHL_LOCATION_ID`

Sono inoltre usati i file di configurazione:
- `config/operators.json`
- `config/calendars.json`

## 🚀 Avvio rapido (systemd)

Il servizio `alfadocs-sync` esegue `deploy.sh production`, fa una sincronizzazione pazienti iniziale e poi entra in un loop infinito (Careplan + GHL). Se esce o va in errore, riparte da solo.

1) Abilitazione una tantum (avvio automatico al boot):
```bash
sudo systemctl enable alfadocs-sync
```

2) Avvio del servizio (parte in background e resta attivo anche a terminale chiuso):
```bash
sudo systemctl start alfadocs-sync
```

3) Stato e log live:
```bash
sudo systemctl status alfadocs-sync
sudo journalctl -fu alfadocs-sync
```

4) Stop/Restart:
```bash
sudo systemctl stop alfadocs-sync
sudo systemctl restart alfadocs-sync
```

Nota: se modifichi `systemd/alfadocs-sync.service`, ricarica systemd e riavvia il servizio:
```bash
sudo systemctl daemon-reload
sudo systemctl restart alfadocs-sync
```

## ▶️ Esecuzione manuale (singolo componente)

Esegui un componente alla volta (utile per test veloci):
```bash
python3 alfadocs_patients_sync.py
python3 alfadocs_careplan_sync.py
python3 ghl_sync.py
```

## 📁 Log utili

- `logs/alfadocs_sync_loop.log` — loop principale e conteggio cicli
- `logs/alfadocs_careplan_sync.log` — sincronizzazione care plan/appuntamenti
- `logs/alfadocs_patients_sync.log` — sincronizzazione pazienti
- `logs/ghl_sync.log` — sincronizzazione verso GHL
- `logs/ghl_sync_errors.log` — errori dettagliati GHL

Per seguire in tempo reale:
```bash
tail -f logs/alfadocs_sync_loop.log
```

## 🗂️ Struttura cartelle (minima)

- `config/` — mapping operatori e calendari (`operators.json`, `calendars.json`)
- `logs/` — tutti i file di log
- `migrations/` — eventuali script SQL per modifiche al database

## ℹ️ Note importanti

- Il servizio parte in automatico all'avvio del server se è "enabled" (`systemctl is-enabled alfadocs-sync`).
- Se esegui manualmente `deploy.sh production` da terminale, chiudendo il terminale il processo si fermerà. Per tenerlo sempre attivo usa systemd.
- I loop girano circa ogni 30 secondi.
- La sincronizzazione pazienti completa può avvenire all'avvio.
- I log sono disponibili anche via Docker (`docker logs -f <nome_container>`).

## 🧭 Comandi equivalenti via script

Per comodità esistono wrapper nello script `deploy.sh`:
```bash
bash deploy.sh start     # Avvia il servizio via systemd
bash deploy.sh stop      # Ferma il servizio via systemd
bash deploy.sh restart   # Riavvia il servizio via systemd
bash deploy.sh status    # Stato systemd
bash deploy.sh logs      # Log systemd in tempo reale
bash deploy.sh loop-logs # Log del loop interno
```

Se sposti la cartella del progetto, verifica/aggiorna i percorsi in `systemd/alfadocs-sync.service` (`WorkingDirectory` e `ExecStart`). Poi esegui:
```bash
sudo cp systemd/alfadocs-sync.service /etc/systemd/system/alfadocs-sync.service
sudo systemctl daemon-reload
sudo systemctl restart alfadocs-sync
```

## 🧰 Comandi utili

```bash
# PID e comando principale del servizio
ps -p $(sudo systemctl show -p MainPID --value alfadocs-sync) -o pid,cmd

# Disabilitare/abilitare l'avvio automatico
sudo systemctl disable alfadocs-sync
sudo systemctl enable alfadocs-sync
```

## ❗ Troubleshooting rapido

- **Credenziali mancanti**: controlla che `.env` contenga tutte le chiavi richieste.
- **DB non raggiungibile**: verifica host/porta/utente nel `.env` e i permessi.
- **Operatori/Calendari non mappati**: aggiorna `config/operators.json` e `config/calendars.json`.
- **Care plan non accessibile (403)**: lo script salta quel care plan e prosegue; controlla `logs/alfadocs_careplan_sync.log`.
- **Errori GHL**: vedi `logs/ghl_sync_errors.log` per il dettaglio della risposta API.
