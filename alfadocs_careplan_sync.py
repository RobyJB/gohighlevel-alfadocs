#!/usr/bin/env python3
"""
Script per sincronizzare i codici care plan (campo 'name') negli appuntamenti da AlfaDocs.
Recupera gli appuntamenti e aggiorna il campo care_plan_code con il nome del care plan associato.
"""

import requests
from datetime import datetime, timedelta
import time
import logging
import hashlib
import json
from typing import Dict, List, Optional
import os
import sys
import signal
import traceback
import psycopg2
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal file .env
load_dotenv()

def log_service_startup(service_name: str):
    """Logga l'avvio del servizio in un file centralizzato"""
    import os
    startup_log_path = 'logs/services_startup.log'
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pid = os.getpid()
    
    # Crea la directory se non esiste
    os.makedirs('logs', exist_ok=True)
    
    with open(startup_log_path, 'a', encoding='utf-8') as f:
        f.write(f"{timestamp} - 🚀 AVVIO SERVIZIO: {service_name} (PID: {pid})\n")

# Configurazione del logger
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/alfadocs_careplan_sync.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class DatabaseManager:
    """Gestore semplificato del database PostgreSQL"""
    
    def __init__(self, logger):
        self.logger = logger
        self.connection = None
        self.connect()
    
    def connect(self):
        """Stabilisce la connessione al database"""
        try:
            self.connection = psycopg2.connect(
                host=os.getenv('DB_HOST'),
                port=os.getenv('DB_PORT'),
                database=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD')
            )
            self.connection.autocommit = True
            self.logger.info("✅ Connessione al database stabilita")
        except Exception as e:
            self.logger.error(f"❌ Errore connessione database: {e}")
            raise
    
    def execute_query(self, query, params=None):
        """Esegue una query e restituisce i risultati"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            if cursor.description:
                return cursor.fetchall()
            return cursor.rowcount
        except Exception as e:
            self.logger.error(f"❌ Errore query: {e}")
            self.logger.error(f"Query: {query}")
            self.logger.error(f"Params: {params}")
            return None
    
    def close(self):
        """Chiude la connessione al database"""
        if self.connection:
            self.connection.close()
            self.logger.info("🔐 Connessione database chiusa")

def signal_handler(signum, frame):
    """Gestisce i segnali di terminazione per chiusura pulita"""
    print("\n🔄 Chiusura pulita in corso...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class AlfaDocsCarePlanSync:
    """Servizio per sincronizzare i codici care plan negli appuntamenti"""
    
    def __init__(self):
        """Inizializza il servizio di sincronizzazione"""
        # Configurazione API AlfaDocs dal file .env
        self.API_KEY = os.getenv('ALFADOCS_API_KEY')
        self.PRACTICE_ID = os.getenv('ALFADOCS_PRACTICE_ID')
        self.ARCHIVE_ID = os.getenv('ALFADOCS_ARCHIVE_ID')
        self.BASE_URL = os.getenv('ALFADOCS_BASE_URL')
        
        if not all([self.API_KEY, self.PRACTICE_ID, self.ARCHIVE_ID, self.BASE_URL]):
            raise ValueError("❌ Credenziali AlfaDocs mancanti nel file .env")
        
        self.headers = {"X-Api-Key": self.API_KEY}
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Initialize database
        self.db = DatabaseManager(self.logger)
        
        self.logger.info("🚀 AlfaDocsCarePlanSync inizializzato")

    def calculate_hash(self, data: Dict) -> str:
        """Calcola un hash dei dati per rilevare modifiche"""
        return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def extract_care_plan_code_from_data(self, care_plan_data: Dict) -> Optional[str]:
        """
        Estrae il primo codice disponibile da care_plan_data, gestendo formati diversi di 'schemeCodes'.
        - Può essere un dict con chiave 'general' o altre chiavi.
        - Può essere direttamente una lista (anche vuota).
        Ritorna una stringa con il codice oppure None se non trovata.
        """
        try:
            scheme_codes = care_plan_data.get('schemeCodes')
            codes_list: List[Dict] = []
            if isinstance(scheme_codes, list):
                codes_list = scheme_codes
            elif isinstance(scheme_codes, dict):
                general_list = scheme_codes.get('general')
                if isinstance(general_list, list) and general_list:
                    codes_list = general_list
                else:
                    first_list = next(iter(scheme_codes.values()), []) if scheme_codes else []
                    codes_list = first_list if isinstance(first_list, list) else []
            else:
                codes_list = []

            if isinstance(codes_list, list) and len(codes_list) > 0:
                first_code = codes_list[0]
                if isinstance(first_code, dict):
                    code_value = first_code.get('code') or first_code.get('name') or ''
                    return code_value.strip() if isinstance(code_value, str) else None
                # Se l'API restituisce liste semplici di stringhe
                if isinstance(first_code, str):
                    return first_code.strip()
            return None
        except Exception as e:
            self.logger.warning(f"⚠️ Impossibile estrarre schemeCodes: {e}")
            return None

    def fetch_appointments(self, start_date: datetime, end_date: datetime) -> Optional[List[Dict]]:
        """
        Recupera gli appuntamenti da AlfaDocs e li salva nel database.
        Poi aggiorna il care_plan_code per quelli che ne hanno bisogno.
        """
        all_appointments = []
        chunk_size = 30  # Massimo intervallo consentito dall'API
        current_start = start_date
        
        self.logger.info(f"🔄 Recupero appuntamenti da AlfaDocs dal {start_date} al {end_date}")
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=chunk_size-1), end_date)
            
            endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/appointments"
            
            params = {
                'dateStart': current_start.strftime("%Y-%m-%d"),
                'dateEnd': current_end.strftime("%Y-%m-%d"),
            }
            
            try:
                response = requests.get(endpoint, headers=self.headers, params=params, timeout=30)
                response.raise_for_status()
                chunk_appointments = response.json().get('data', [])
                
                # Filtra solo gli appuntamenti validi (con paziente e operatore)
                valid_appointments = [
                    appointment for appointment in chunk_appointments
                    if (
                        appointment.get('patientId') is not None and
                        appointment.get('operatorId') is not None
                    )
                ]
                
                # Salva o aggiorna gli appuntamenti nel database (con care plan codes)
                saved_count = 0
                for idx, appointment in enumerate(valid_appointments, 1):
                    if self.save_or_update_appointment(appointment):
                        saved_count += 1
                    
                    # Rate limiting più frequente per gestire le chiamate ai care plan
                    if idx % 5 == 0:  # Pausa ogni 5 appuntamenti
                        time.sleep(0.3)
                
                self.logger.info(f"✅ Salvati {saved_count}/{len(valid_appointments)} appuntamenti per intervallo {current_start} - {current_end}")
                all_appointments.extend(valid_appointments)
                
                time.sleep(0.5)  # Rate limiting tra i chunk di date
                
            except Exception as e:
                self.logger.error(f"❌ Errore recupero appuntamenti per intervallo {current_start} - {current_end}: {e}")
            
            current_start = current_end + timedelta(days=1)
        
        self.logger.info(f"✅ Totale appuntamenti recuperati da AlfaDocs: {len(all_appointments)}")
        return all_appointments

    def save_or_update_appointment(self, appointment: Dict) -> bool:
        """Salva o aggiorna un appuntamento nel database, recuperando prima il care plan code se necessario"""
        try:
            # Prepara i dati per il database
            appointment_id = appointment.get('id')
            patient_id = appointment.get('patientId')
            operator_id = appointment.get('operatorId')
            care_plan_id = appointment.get('carePlanId')
            
            # Mantengo solo inizializzazione del care_plan_code
            care_plan_code = None
            
            # Verifica se il paziente esiste nella tabella 'patients', altrimenti lo recupera e lo inserisce
            if patient_id:
                self.logger.debug(f"🔍 Controllo esistenza paziente {patient_id}")
                if not self.ensure_patient_exists(patient_id):
                    self.logger.warning(f"⚠️ Paziente {patient_id} non trovato e non inserito, salto appuntamento {appointment_id}")
                    return False
            
            # NUOVO: Recupero del care_plan_code dopo aver verificato il paziente
            if care_plan_id:
                self.logger.debug(f"🔍 Recupero care plan {care_plan_id} per appuntamento {appointment_id}")
                care_plan_data = self.fetch_care_plan(care_plan_id)
                if care_plan_data:
                    # Estrae il codice con gestione robusta di schemeCodes (dict o lista)
                    care_plan_code_extracted = self.extract_care_plan_code_from_data(care_plan_data)
                    if care_plan_code_extracted:
                        care_plan_code = care_plan_code_extracted
                        self.logger.info(f"✅ Care plan code '{care_plan_code}' recuperato per appuntamento {appointment_id}")
                    else:
                        self.logger.warning(f"⚠️ Care plan {care_plan_id} senza codici per appuntamento {appointment_id}")
                        self._debug_care_plan_without_codes(appointment, care_plan_data)
                else:
                    self.logger.warning(f"⚠️ Impossibile recuperare care plan {care_plan_id} per appuntamento {appointment_id}")

            # Nota: rimosso il secondo recupero/estrazione duplicato del care plan
            
            appointment_date = datetime.fromisoformat(appointment.get('date').replace('Z', '+00:00'))
            
            # Estrai tutti i campi disponibili
            email_reminder = appointment.get('emailReminder')
            sms_reminder = appointment.get('smsReminder')
            description = appointment.get('description')
            all_day = appointment.get('allDay')
            appointment_type = appointment.get('type')
            state = appointment.get('state')
            duration = appointment.get('duration')
            color_id = appointment.get('colorId')
            frequency = appointment.get('frequency')
            recurrence_count = appointment.get('recurrenceCount')
            chair_id = appointment.get('chairId')
            created_through_booking = appointment.get('createdThroughBooking')
            created_through_api = appointment.get('createdThroughApi')
            first_visit = appointment.get('firstVisit')
            
            # Verifica i valori esistenti nel database
            self.logger.debug(f"Verifica valori esistenti per appuntamento {appointment_id}")
            result = self.db.execute_query("""
                SELECT appointment_date, operator_id, state, hash_value 
                FROM appointments WHERE id = %s
            """, (appointment_id,))

            old_values = result[0] if result else None
            self.logger.debug(f"Valori esistenti per appuntamento {appointment_id}: {old_values}")
            
            # Calcola l'hash dei dati attuali
            current_hash = self.calculate_hash(appointment)
            
            # Verifica se i campi critici sono cambiati
            # Se l'appuntamento esiste già ed è già marcato per sync, preservo il true
            preserve_flag_true = False
            if result and len(result) > 0:
                # Recupero lo state dei flag correnti
                existing_should_sync = self.db.execute_query(
                    "SELECT should_sync_to_ghl FROM appointments WHERE id = %s",
                    (appointment_id,)
                )
                if existing_should_sync and len(existing_should_sync) > 0:
                    preserve_flag_true = bool(existing_should_sync[0][0])

            needs_sync = preserve_flag_true or (not old_values or (
                str(old_values[0]) != str(appointment_date) or  # Data appuntamento
                old_values[1] != operator_id or                # Operatore
                old_values[2] != state                        # Stato
            ))
            
            # Log dettagliato dei dati
            self.logger.info(f"""
📝 Dati appuntamento da salvare:
   - ID: {appointment_id}
   - Paziente: {patient_id}
   - Operatore: {operator_id}
   - Care Plan: {care_plan_id}
   - Care Plan Code: {care_plan_code}
   - Data: {appointment_date}
   - Stato: {state}
   - Email Reminder: {email_reminder}
   - SMS Reminder: {sms_reminder}
   - Descrizione: {description}
   - All Day: {all_day}
   - Tipo: {appointment_type}
   - Durata: {duration}
   - Color ID: {color_id}
   - Frequenza: {frequency}
   - Conteggio Ricorrenza: {recurrence_count}
   - Chair ID: {chair_id}
   - Creato da Booking: {created_through_booking}
   - Creato da API: {created_through_api}
   - Prima Visita: {first_visit}
   - Deve sincronizzare con GHL: {needs_sync}
""")
            
            # Query per inserire o aggiornare l'appuntamento con tutti i campi INCLUSO care_plan_code
            query = """
                INSERT INTO appointments (
                    id, patient_id, operator_id, care_plan_id, care_plan_code,
                    appointment_date, email_reminder, sms_reminder,
                    description, all_day, appointment_type, state,
                    duration, color_id, frequency, recurrence_count,
                    chair_id, created_through_booking, created_through_api,
                    first_visit, created_at, updated_at, hash_value,
                    should_sync_to_ghl
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    patient_id = EXCLUDED.patient_id,
                    operator_id = EXCLUDED.operator_id,
                    care_plan_id = EXCLUDED.care_plan_id,
                    care_plan_code = EXCLUDED.care_plan_code,
                    appointment_date = EXCLUDED.appointment_date,
                    email_reminder = EXCLUDED.email_reminder,
                    sms_reminder = EXCLUDED.sms_reminder,
                    description = EXCLUDED.description,
                    all_day = EXCLUDED.all_day,
                    appointment_type = EXCLUDED.appointment_type,
                    state = EXCLUDED.state,
                    duration = EXCLUDED.duration,
                    color_id = EXCLUDED.color_id,
                    frequency = EXCLUDED.frequency,
                    recurrence_count = EXCLUDED.recurrence_count,
                    chair_id = EXCLUDED.chair_id,
                    created_through_booking = EXCLUDED.created_through_booking,
                    created_through_api = EXCLUDED.created_through_api,
                    first_visit = EXCLUDED.first_visit,
                    updated_at = CURRENT_TIMESTAMP,
                    hash_value = EXCLUDED.hash_value,
                    should_sync_to_ghl = EXCLUDED.should_sync_to_ghl
                RETURNING id, care_plan_id, care_plan_code, description, state, duration, should_sync_to_ghl
            """
            
            # Parametri per la query INCLUSO care_plan_code
            params = (
                appointment_id, patient_id, operator_id, care_plan_id, care_plan_code,
                appointment_date, email_reminder, sms_reminder,
                description, all_day, appointment_type, state,
                duration, color_id, frequency, recurrence_count,
                chair_id, created_through_booking, created_through_api,
                first_visit, current_hash, needs_sync
            )
            
            # Log della query
            self.logger.debug(f"🔍 Query SQL: {query}")
            self.logger.debug(f"📊 Parametri: {params}")
            
            result = self.db.execute_query(query, params)
            
            if result:
                # Log del risultato
                self.logger.info(f"""
✅ Appuntamento salvato/aggiornato:
   - ID: {result[0][0] if result else 'N/A'}
   - Care Plan ID: {result[0][1] if result else 'N/A'}
   - Care Plan Code: {result[0][2] if result else 'N/A'}
   - Descrizione: {result[0][3] if result else 'N/A'}
   - Stato: {result[0][4] if result else 'N/A'}
   - Durata: {result[0][5] if result else 'N/A'}
   - Deve sincronizzare con GHL: {result[0][6] if result else 'N/A'}
""")
                return True
            else:
                self.logger.warning(f"""
⚠️ Errore salvataggio appuntamento:
   - ID: {appointment_id}
   - Query eseguita ma nessun risultato restituito
""")
                return False
                
        except Exception as e:
            self.logger.error(f"""
❌ Errore salvataggio appuntamento {appointment.get('id')}:
   - Errore: {str(e)}
   - Dati: {json.dumps(appointment, indent=2, ensure_ascii=False)}
""")
            return False

    def _debug_care_plan_without_codes(self, appointment: Dict, care_plan_data: Dict):
        """Metodo separato per il debug completo quando care plan non ha schemeCodes"""
        appointment_id = appointment.get('id')
        care_plan_id = appointment.get('carePlanId')
        patient_id = appointment.get('patientId')
        
        self.logger.error("🔍 === DEBUG CARE PLAN SENZA SCHEME CODES ===")
        
        # 1. Log richiesta originale appuntamenti
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=4)
        end_date = start_date + timedelta(days=365 * 4)
        appointments_endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/appointments"
        appointments_params = {
            'dateStart': start_date.strftime("%Y-%m-%d"),
            'dateEnd': end_date.strftime("%Y-%m-%d"),
        }
        self.logger.error(f"📋 APPUNTAMENTI - Richiesta API originale:")
        self.logger.error(f"   - URL: {appointments_endpoint}")
        self.logger.error(f"   - Headers: {json.dumps(self.headers, indent=2, ensure_ascii=False)}")
        self.logger.error(f"   - Params: {json.dumps(appointments_params, indent=2, ensure_ascii=False)}")
        
        # 2. Log dati dell'appuntamento completo
        self.logger.error(f"📋 APPUNTAMENTO {appointment_id} - Dati dalla risposta API:")
        self.logger.error(f"   - JSON completo: {json.dumps(appointment, indent=2, ensure_ascii=False)}")
        
        # 3. Log dati del care plan completo
        self.logger.error(f"📋 CARE PLAN {care_plan_id} - Richiesta API:")
        care_plan_endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/care-plans/{care_plan_id}"
        self.logger.error(f"   - URL: {care_plan_endpoint}")
        self.logger.error(f"   - Headers: {json.dumps(self.headers, indent=2, ensure_ascii=False)}")
        self.logger.error(f"📋 CARE PLAN {care_plan_id} - Risposta API:")
        self.logger.error(f"   - JSON completo: {json.dumps(care_plan_data, indent=2, ensure_ascii=False)}")
        
        # 4. Log dati del paziente completo
        if patient_id:
            self.logger.error(f"📋 PAZIENTE {patient_id} - Debug completo...")
            patient_debug_data = self.fetch_patient_debug(patient_id)
            if patient_debug_data:
                self.logger.error(f"📋 PAZIENTE {patient_id} - Richiesta API:")
                patient_endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/patients/{patient_id}"
                self.logger.error(f"   - URL: {patient_endpoint}")
                self.logger.error(f"   - Headers: {json.dumps(self.headers, indent=2, ensure_ascii=False)}")
                self.logger.error(f"📋 PAZIENTE {patient_id} - Risposta API:")
                self.logger.error(f"   - JSON completo: {json.dumps(patient_debug_data, indent=2, ensure_ascii=False)}")
        
        self.logger.error("🔍 === FINE DEBUG CARE PLAN SENZA SCHEME CODES ===")

    def fetch_care_plan(self, care_plan_id: int) -> Optional[Dict]:
        """Recupera i dettagli di un care plan e estrae il campo 'name'"""
        endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/care-plans/{care_plan_id}"
        
        try:
            self.logger.debug(f"🔍 Recupero care plan {care_plan_id}...")
            
            response = requests.get(endpoint, headers=self.headers, timeout=15)
            
            # Gestione specifica degli errori 403 - care plan non accessibili
            if response.status_code == 403:
                self.logger.warning(f"⚠️ Care plan {care_plan_id} non accessibile (403 Forbidden) - SALTO")
                return None
            
            # Gestione altri errori HTTP
            if response.status_code >= 400:
                self.logger.error(f"❌ Errore HTTP {response.status_code} per care plan {care_plan_id} - SALTO")
                return None
                
            response.raise_for_status()
            care_plan_data = response.json().get('data')
            
            if not care_plan_data:
                self.logger.warning(f"⚠️ Nessun dato ricevuto per care plan {care_plan_id}")
                return None
                
            self.logger.debug(f"✅ Care plan {care_plan_id} recuperato: '{care_plan_data.get('name', 'N/A')}'")
            return care_plan_data
                
        except requests.exceptions.Timeout:
            self.logger.error(f"❌ Timeout recupero care plan {care_plan_id} - SALTO")
            return None
        except requests.exceptions.ConnectionError:
            self.logger.error(f"❌ Errore connessione per care plan {care_plan_id} - SALTO")
            return None
        except Exception as e:
            self.logger.error(f"❌ Errore generico recupero care plan {care_plan_id}: {e} - SALTO")
            return None

    def update_appointment_care_plan_code(self, appointment_id: int, care_plan_code: str) -> bool:
        """
        DEPRECATO: Questo metodo non è più necessario perché il care_plan_code 
        viene ora impostato direttamente durante il salvataggio dell'appuntamento.
        Mantenuto per compatibilità.
        """
        self.logger.warning(f"⚠️ Metodo update_appointment_care_plan_code è deprecato per appuntamento {appointment_id}")
        return True

    def fetch_patient(self, patient_id: int) -> Optional[Dict]:
        """Recupera i dettagli di un paziente da AlfaDocs."""
        endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/patients/{patient_id}"
        try:
            self.logger.debug(f"🔍 Recupero paziente {patient_id}...")
            response = requests.get(endpoint, headers=self.headers, timeout=30)
            response.raise_for_status()
            patient_data = response.json().get('data')
            if not patient_data:
                self.logger.warning(f"⚠️ Nessun dato ricevuto per paziente {patient_id}")
                return None
            self.logger.debug(f"✅ Paziente {patient_id} recuperato: {patient_data}")
            return patient_data
        except Exception as e:
            self.logger.error(f"❌ Errore recupero paziente {patient_id}: {e}")
            return None

    def fetch_patient_debug(self, patient_id: int) -> Optional[Dict]:
        """Recupera i dettagli di un paziente per debug completo quando care plan non ha schemeCodes."""
        endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/patients/{patient_id}"
        try:
            self.logger.debug(f"🔍 DEBUG: Recupero paziente {patient_id}...")
            response = requests.get(endpoint, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            # Restituisce la risposta completa per il debug
            full_response = response.json()
            return full_response
        except Exception as e:
            self.logger.error(f"❌ Errore DEBUG recupero paziente {patient_id}: {e}")
            return None

    def ensure_patient_exists(self, patient_id: int) -> bool:
        """Verifica se il paziente esiste nel database, altrimenti lo recupera e lo inserisce."""
        result = self.db.execute_query("SELECT id FROM patients WHERE id = %s", (patient_id,))
        if result and len(result) > 0:
            return True
        # Recupera dati paziente da AlfaDocs
        patient_data = self.fetch_patient(patient_id)
        if not patient_data:
            return False
        # Mappatura dei campi del paziente
        first_name = patient_data.get('firstName')
        last_name = patient_data.get('lastName')
        email = patient_data.get('email')
        email_enabled = patient_data.get('emailEnabled')
        email_valid = patient_data.get('emailValid')
        phone_numbers = patient_data.get('phoneNumbers', [])
        primary_phone = None
        secondary_phone = None
        if len(phone_numbers) > 0:
            primary_phone = f"{phone_numbers[0].get('prefix','')}{phone_numbers[0].get('number','')}"
        if len(phone_numbers) > 1:
            secondary_phone = f"{phone_numbers[1].get('prefix','')}{phone_numbers[1].get('number','')}"
        gender = patient_data.get('gender')
        street = patient_data.get('street')
        city = patient_data.get('city')
        postcode = patient_data.get('postcode')
        province = patient_data.get('province')
        date_birth = patient_data.get('dateBirth')
        place_of_birth = patient_data.get('placeOfBirth')
        italian_fiscal_code = patient_data.get('italianFiscalCode')
        job = patient_data.get('job')
        yearly_numbering_year = patient_data.get('yearlyNumberingYear')
        yearly_numbering_number = patient_data.get('yearlyNumberingNumber')
        default_discount = patient_data.get('defaultDiscount')
        source_id = patient_data.get('sourceId')
        price_list_id = patient_data.get('priceListId')
        email_reminder_possible = patient_data.get('emailReminderPossible')
        sms_reminder_possible = patient_data.get('smsReminderPossible')
        created_at = patient_data.get('createdAt')
        document_signature_email_possible = patient_data.get('documentSignatureEmailPossible')
        last_modified_at = patient_data.get('lastModifiedAt')
        last_synced_at = datetime.now()
        hash_value = self.calculate_hash(patient_data)
        needs_sync = True
        ghl_contact_id = None
        # Inserimento nel database
        insert_query = """
            INSERT INTO patients (
                id, first_name, last_name, email, email_enabled, email_valid,
                primary_phone, secondary_phone, gender, street, city, postcode,
                province, date_birth, place_of_birth, italian_fiscal_code,
                job, yearly_numbering_year, yearly_numbering_number,
                default_discount, source_id, price_list_id,
                email_reminder_possible, sms_reminder_possible,
                created_at, document_signature_email_possible,
                last_modified_at, last_synced_at, hash_value, needs_sync, ghl_contact_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s, %s
            )
        """
        params = (
            patient_id, first_name, last_name, email, email_enabled, email_valid,
            primary_phone, secondary_phone, gender, street, city, postcode,
            province, date_birth, place_of_birth, italian_fiscal_code,
            job, yearly_numbering_year, yearly_numbering_number,
            default_discount, source_id, price_list_id,
            email_reminder_possible, sms_reminder_possible,
            created_at, document_signature_email_possible,
            last_modified_at, last_synced_at, hash_value, needs_sync, ghl_contact_id
        )
        insert_result = self.db.execute_query(insert_query, params)
        if insert_result is not None:
            self.logger.info(f"✅ Paziente {patient_id} inserito nel database")
            return True
        else:
            self.logger.error(f"❌ Errore inserimento paziente {patient_id} nel database")
            return False

    def sync_care_plan_codes(self):
        """
        Funzione principale di sincronizzazione dei codici care plan.
        Ora i care plan codes vengono recuperati direttamente durante il salvataggio degli appuntamenti.
        
        Returns:
            bool: True se la sincronizzazione è avvenuta con successo
            
        Raises:
            Exception: In caso di errori critici durante la sincronizzazione
        """
        # Intervallo di date: da 4 giorni fa a 4 anni nel futuro
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=4)
        end_date = start_date + timedelta(days=365 * 4)
        
        self.logger.info(f"🚀 Inizio sincronizzazione appuntamenti con care plan codes dal {start_date} al {end_date}")
        
        sync_start_time = datetime.now()
        stats = {
            'appointments_processed': 0,
            'appointments_saved': 0,
            'api_calls_made': 0,
            'errors_count': 0
        }
        
        try:
            # Questo metodo ora recupera gli appuntamenti E li salva con i care plan codes
            appointments = self.fetch_appointments(start_date, end_date)
            
            if not appointments:
                self.logger.info("✅ Nessun appuntamento da processare")
                return True
            
            # Le statistiche vengono aggiornate durante fetch_appointments
            stats['appointments_processed'] = len(appointments)
            
            # Log finale
            sync_duration = datetime.now() - sync_start_time
            self.logger.info("🎉 Sincronizzazione completata con successo!")
            self.logger.info(f"📊 Statistiche finali:")
            self.logger.info(f"   - Appuntamenti processati: {stats['appointments_processed']}")
            self.logger.info(f"   - Durata: {sync_duration}")
            
            return True
            
        except requests.exceptions.RequestException as e:
            error_message = f"❌ Errore di comunicazione con AlfaDocs API: {str(e)}"
            self.logger.error(error_message)
            raise Exception(error_message)
        except psycopg2.Error as e:
            error_message = f"❌ Errore del database: {str(e)}"
            self.logger.error(error_message)
            raise Exception(error_message)
        except Exception as e:
            error_message = f"❌ Errore imprevisto durante la sincronizzazione: {str(e)}"
            self.logger.error(error_message)
            self.logger.error(traceback.format_exc())
            raise Exception(error_message)

def main():
    """Funzione principale che avvia il servizio di sincronizzazione"""
    # Log di avvio centralizzato
    log_service_startup("ALFADOCS-CAREPLAN-SYNC")
    
    sync_service = AlfaDocsCarePlanSync()
    try:
        # Esegue la sincronizzazione completa
        sync_service.sync_care_plan_codes()
    except Exception as e:
        print(f"❌ Errore durante la sincronizzazione: {e}")
        return 1
    finally:
        sync_service.db.close()
    return 0

if __name__ == '__main__':
    sys.exit(main()) 