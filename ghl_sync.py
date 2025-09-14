#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script per sincronizzare contatti e appuntamenti su Go High Level (GHL/Squadd).
Le credenziali vengono lette dal file .env.
"""

import os
import sys
import json
import time
import logging
import traceback
import requests
import psycopg2
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
import pytz

# Carico le variabili d'ambiente dal file .env
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

# ========== Configurazione credenziali dal file .env ==========
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
GHL_LOCATION_ID = os.getenv("GHL_LOCATION_ID")

# Verifico che tutte le credenziali siano presenti
if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, GHL_LOCATION_ID]):
    print("Errore: variabili di ambiente mancanti nel file .env")
    sys.exit(1)

# ========== Configurazione del logger ==========
logger = logging.getLogger("ghl_sync")
logger.setLevel(logging.INFO)
# Creo cartella per i log se non esiste
os.makedirs("logs", exist_ok=True)
# Handler per i log generali
file_handler = logging.FileHandler("logs/ghl_sync.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(file_handler)
# Handler per i log di errore
error_handler = logging.FileHandler("logs/ghl_sync_errors.log", encoding="utf-8")
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(error_handler)
# Handler per la console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(console_handler)


class DatabaseManager:
    """
    Gestore PostgreSQL: connette, esegue query e chiude la connessione.
    """
    def __init__(self):
        # Stabilisco la connessione al database
        try:
            self.connection = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            self.connection.autocommit = True
            logger.info("Connessione al database stabilita")
        except Exception as e:
            logger.error(f"Errore connessione database: {e}")
            raise

    def execute_query(self, query, params=None):
        """
        Esegue una query SQL.
        Restituisce i risultati o il numero di righe interessate.
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                if cursor.description:
                    return cursor.fetchall()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Errore query database: {e}")
            logger.error(f"Query: {query}")
            return None

    def close(self):
        """
        Chiude la connessione al database.
        """
        if hasattr(self, "connection") and self.connection:
            self.connection.close()
            logger.info("Connessione database chiusa")


class GHLSyncService:
    """
    Servizio per sincronizzare contatti e appuntamenti su GHL.
    Include autenticazione, pulizia dati e chiamate API.
    """
    def __init__(self):
        # Imposto la location ID per GHL
        self.location_id = GHL_LOCATION_ID
        # Token di accesso e scadenza
        self._access_token = None
        self._token_expires_at = None
        # Timestamps per gestire il rate limiting
        self._requests_timestamps = []
        # Inizializzo il database
        self.db = DatabaseManager()
        # Carico le configurazioni da file JSON
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_dir = os.path.join(base_dir, "config")
        with open(os.path.join(config_dir, "operators.json"), "r", encoding="utf-8") as f:
            self.operators = json.load(f)
        with open(os.path.join(config_dir, "calendars.json"), "r", encoding="utf-8") as f:
            self.calendars = json.load(f)
        logger.info("GHLSyncService inizializzato")

    def _get_access_token(self, force_refresh=False):
        """
        Ottiene o rinnova il token di accesso per GHL.
        """
        if not force_refresh and self._access_token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._access_token

        try:
            logger.debug("Richiedo nuovo token di accesso")
            url = "https://portal.squaddcrm.com/oauth/refresh"
            payload = {"location_id": self.location_id}
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code != 200:
                raise Exception(f"{response.status_code} - {response.text}")
            data = response.json()
            token = data.get("access_token")
            if not token:
                raise Exception("token non trovato nella risposta")
            # Salvo token e scadenza (24h)
            self._access_token = token
            self._token_expires_at = datetime.now() + timedelta(hours=24)
            logger.info("Token di accesso ottenuto")
            return token
        except Exception as e:
            logger.error(f"Errore ottenimento token: {e}")
            raise

    def _make_request(self, method, url, **kwargs):
        """
        Esegue la chiamata HTTP con gestione automatica del token.
        """
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"]["Authorization"] = f"Bearer {self._get_access_token()}"
        kwargs["headers"]["Version"] = "2021-07-28"
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 401:
                # Token scaduto, rinnovo e riprovo
                logger.info("Token scaduto, rinnovo e riprovo")
                kwargs["headers"]["Authorization"] = f"Bearer {self._get_access_token(force_refresh=True)}"
                resp = requests.request(method, url, **kwargs)
            return resp
        except Exception as e:
            logger.error(f"Errore richiesta HTTP: {e}")
            raise

    def _format_name(self, name):
        """
        Format del nome (prima lettera maiuscola).
        """
        return name.strip().title() if name else ""

    def _clean_phone(self, phone):
        """
        Pulisce e verifica il numero di telefono.
        Restituisce None se invalido.
        """
        if not phone:
            return None
        nums = "".join(c for c in phone if c.isdigit() or c == "+")
        if nums.startswith("+39+39"):
            nums = "+39" + nums[6:]
        elif not nums.startswith("+"):
            nums = "+39" + nums
        return nums if 10 <= len(nums) <= 13 else None

    def _clean_email(self, email):
        """
        Pulisce e valida l'email di base.
        Restituisce None se invalida.
        """
        if not email:
            return None
        try:
            email = email.strip().lower()
            import re
            pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            return email if re.match(pattern, email) else None
        except Exception as e:
            logger.error(f"Errore pulizia email: {e}")
            return None

    def _calculate_age(self, date_birth):
        """
        Calcola l'età a partire da una data di nascita YYYY-MM-DD.
        """
        if not date_birth:
            return None
        try:
            bd = datetime.strptime(date_birth, "%Y-%m-%d")
            today = datetime.now()
            age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
            return age
        except:
            return None

    def _rate_limit(self):
        """
        Garantisce almeno 1.5 secondi tra le chiamate HTTP.
        """
        now = time.time()
        self._requests_timestamps = [ts for ts in self._requests_timestamps if now - ts < 60]
        if self._requests_timestamps:
            wait = max(0, 1.5 - (now - self._requests_timestamps[-1]))
            if wait > 0:
                time.sleep(wait)
        self._requests_timestamps.append(time.time())

    def _get_calendar_id(self, prestazione_code, label, age):
        """
        Sceglie il calendar ID in base al care_plan_code case-insensitive
        usando config/calendars.json.
        """
        # Imposto default
        default = self.calendars.get("default_calendar_id")
        # Se non è definito care_plan_code, uso default
        if not prestazione_code:
            logger.info(f"care_plan_code vuoto, uso default {default}")
            return default
        # Codice in uppercase per comparazione case-insensitive
        code = prestazione_code.strip().upper()
        # 1) mapping speciale: scelgo under18 o over18 in base all'età del paziente
        specials = self.calendars.get("special_labels", {})
        if code in specials:
            props = specials[code]
            # se ha almeno 18 anni utilizzo il calendario over18, altrimenti under18
            if age is not None and age >= 18:
                cal_id = props.get("over18")
            else:
                cal_id = props.get("under18")
            logger.info(f"Mapping calendario speciale per code {code}: {cal_id}")
            return cal_id
        # 2) mapping diretto dalle prestazioni
        prest_map = self.calendars.get("prestazioni", {})
        if code in prest_map:
            cal_id = prest_map[code].get("calendario_id")
            logger.info(f"Mapping calendario per code {code}: {cal_id}")
            return cal_id
        # 3) fallback default se non trovato
        logger.info(f"care_plan_code {code} non trovato, uso default {default}")
        return default

    def _upsert_contact(self, patient_data):
        """
        Crea o aggiorna un contatto in GHL partendo dal paziente.
        """
        logger.info(f"Upsert contatto paziente {patient_data['id']}")
        try:
            result = self.db.execute_query(
                "SELECT ghl_contact_id FROM patients WHERE id = %s",
                (patient_data['id'],)
            )
            if result and result[0][0]:
                return result[0][0]
            # Preparo data di nascita
            dob = patient_data.get('date_birth')
            if isinstance(dob, (datetime, date)):
                dob = dob.strftime('%Y-%m-%d')
            else:
                dob = str(dob or '')
            # Pulizia dati
            email = self._clean_email(patient_data.get('email'))
            phone = self._clean_phone(patient_data.get('primary_phone'))
            sec_phone = self._clean_phone(patient_data.get('secondary_phone'))
            # Se email non valida, marco per risincronizzazione
            if patient_data.get('email') and not email:
                self.db.execute_query(
                    "UPDATE patients SET needs_sync = true WHERE id = %s",
                    (patient_data['id'],)
                )
                logger.info(f"Paziente {patient_data['id']} marcato per risincronizzazione (email invalida)")
                return None
            # Costruisco il payload per il contatto
            payload = {
                'locationId': self.location_id,
                'firstName': self._format_name(patient_data.get('first_name')) or 'Non specificato',
                'lastName': self._format_name(patient_data.get('last_name')) or 'Non specificato',
                'email': email,
                'phone': phone,
                'dateOfBirth': dob or None,
                'address1': patient_data.get('street'),
                'city': patient_data.get('city'),
                'postalCode': patient_data.get('postcode'),
                'state': patient_data.get('province'),
                'customFields': [
                    {'id': 'luogo_di_nascita', 'value': patient_data.get('place_of_birth')},
                    {'id': 'codice_fiscale', 'value': patient_data.get('italian_fiscal_code')},
                    {'id': 'genere', 'value': 'Maschio' if patient_data.get('gender') == 'm' else 'Femmina'},
                    {'id': 'telefono_secondario', 'value': sec_phone},
                    {'id': 'et_anni', 'value': str(self._calculate_age(dob)) if dob else None}
                ]
            }
            # Applico rate limit prima della chiamata
            self._rate_limit()
            # Rimuovo campi vuoti
            payload = {k: v for k, v in payload.items() if v is not None and v != ''}
            payload['customFields'] = [f for f in payload['customFields'] if f['value']]
            logger.info(f"Payload contatto: {json.dumps(payload, indent=2)}")
            response = self._make_request(
                'POST',
                'https://services.leadconnectorhq.com/contacts',
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            contact_id = data.get('contact', {}).get('id')
            if contact_id:
                self.db.execute_query(
                    "UPDATE patients SET ghl_contact_id = %s, needs_sync = false WHERE id = %s",
                    (contact_id, patient_data['id'])
                )
                logger.info(f"Contatto creato/aggiornato: {contact_id}")
                return contact_id
        except Exception as e:
            # In caso di errore marco per risincronizzazione
            self.db.execute_query(
                "UPDATE patients SET needs_sync = true WHERE id = %s",
                (patient_data['id'],)
            )
            logger.error(f"Errore creazione contatto per paziente {patient_data['id']}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
        return None

    def _create_or_update_appointment(self, appt, contact_id, calendar_id):
        """
        Crea o aggiorna un appuntamento in GHL.
        """
        # Definisce il timezone dell'account (Europe/Amsterdam)
        account_tz = pytz.timezone('Europe/Amsterdam')
        
        # Preparo data di inizio/fine
        start = appt['appointment_date']
        if isinstance(start, datetime):
            # Se il datetime non ha timezone, assume che sia già nel timezone dell'account
            if start.tzinfo is None:
                start = account_tz.localize(start)
            
            # Converti in UTC per l'API GHL
            start_utc = start.astimezone(pytz.UTC)
            logger.debug(f"Orario convertito da {start} a UTC: {start_utc}")
            start = start_utc
        
        end = start + timedelta(minutes=appt.get('duration') or 30)
        # Mappo lo stato locale a quello GHL
        state_map = {
            'waiting': 'new', None: 'confirmed', 'confirmed': 'confirmed',
            'cancelled': 'cancelled', 'in_care': 'confirmed',
            'done': 'showed', 'absent': 'noshow'
        }
        status = state_map.get(appt.get('state'), 'invalid')
        # Titolo e descrizione
        title = appt.get('description') or 'Appuntamento'
        if '\n' in title:
            title = title.replace('\n', ' | ')
        # Assegno operatore
        assigned = self.operators.get(str(appt.get('operator_id')))
        # Costruisco payload
        payload = {
            'calendarId': calendar_id,
            'contactId': contact_id,
            'locationId': self.location_id,
            'startTime': start.isoformat(),
            'endTime': end.isoformat(),
            'title': title,
            'appointmentStatus': status,
            'assignedUserId': assigned,
            'ignoreDateRange': True,
            'toNotify': False,
            'ignoreFreeSlotValidation': True
        }
        logger.info(f"Payload appuntamento: {json.dumps(payload, indent=2)}")
        try:
            self._rate_limit()
            if appt.get('ghl_appointment_id'):
                url = f"https://services.leadconnectorhq.com/calendars/events/appointments/{appt['ghl_appointment_id']}"
                logger.info(f"Aggiornamento appuntamento esistente GHL ID: {appt['ghl_appointment_id']}")
                resp = self._make_request('PUT', url, json=payload)
            else:
                url = 'https://services.leadconnectorhq.com/calendars/events/appointments'
                logger.info(f"Creazione nuovo appuntamento GHL")
                resp = self._make_request('POST', url, json=payload)
            resp.raise_for_status()
            res = resp.json()
            logger.info(f"Risposta GHL per appuntamento {appt['appointment_id']}: {json.dumps(res, indent=2)}")
            new_id = res.get('id')
            # Aggiorno il DB
            self.db.execute_query(
                "UPDATE appointments SET ghl_appointment_id = %s, should_sync_to_ghl = false WHERE id = %s",
                (new_id, appt['appointment_id'])
            )
            logger.info(f"Appuntamento sincronizzato: {new_id}")
            return True
        except Exception as e:
            logger.error(f"Errore sync appuntamento {appt['appointment_id']}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            # Marco per ritentare
            self.db.execute_query(
                "UPDATE appointments SET should_sync_to_ghl = true WHERE id = %s",
                (appt['appointment_id'],)
            )
            return False

    def _delete_appointment(self, ghl_id):
        """
        Elimina un appuntamento in GHL.
        """
        try:
            self._rate_limit()
            url = f"https://services.leadconnectorhq.com/calendars/events/{ghl_id}"
            resp = self._make_request('DELETE', url)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Errore eliminazione appuntamento {ghl_id}: {e}")
            return False

    def sync_appointments(self):
        """
        Sincronizza gli appuntamenti recenti con GHL.
        """
        logger.info("Inizio sincronizzazione appuntamenti...")
        # Query per selezionare appuntamenti
        query = """
        SELECT
            a.id AS appointment_id,
            a.appointment_date,
            a.patient_id,
            a.care_plan_id,
            a.care_plan_code AS care_plan_code,
            a.description,
            a.duration,
            a.operator_id,
            a.state,
            a.ghl_appointment_id,
            p.first_name,
            p.last_name,
            p.email,
            p.primary_phone,
            p.secondary_phone,
            p.gender,
            p.street,
            p.city,
            p.postcode,
            p.province,
            p.date_birth,
            p.place_of_birth,
            p.italian_fiscal_code,
            t.code AS prestazione_code,
            c.label
        FROM appointments a
        INNER JOIN patients p ON a.patient_id = p.id
        LEFT JOIN treatment_codes t ON a.id = t.appointment_id
        LEFT JOIN careplan_entries c ON a.id = c.appointment_id
        WHERE a.should_sync_to_ghl = true
          AND a.operator_id IS NOT NULL
          AND a.operator_id != 308357
          AND (a.state = 'confirmed' OR a.state IS NULL OR a.state = '' OR a.state = 'done' OR a.state = 'absent')
        ORDER BY a.appointment_date;
        """
        appointments = self.db.execute_query(query)
        if not appointments:
            logger.info("Nessun appuntamento da sincronizzare")
            return True
        # Rimuovo gli appuntamenti cancellati
        cancelled = self.db.execute_query(
            "SELECT id, ghl_appointment_id FROM appointments WHERE state = 'cancelled' AND ghl_appointment_id IS NOT NULL"
        )
        for app_id, ghl_id in cancelled or []:
            if self._delete_appointment(ghl_id):
                self.db.execute_query(
                    "UPDATE appointments SET ghl_appointment_id = NULL WHERE id = %s",
                    (app_id,)
                )
        # Nomino le colonne per mappare i risultati
        column_names = [
            'appointment_id','appointment_date','patient_id','care_plan_id','care_plan_code',
            'description','duration','operator_id','state','ghl_appointment_id',
            'first_name','last_name','email','primary_phone','secondary_phone',
            'gender','street','city','postcode','province','date_birth',
            'place_of_birth','italian_fiscal_code','prestazione_code','label'
        ]
        total = len(appointments)
        # Ciclo sugli appuntamenti da sincronizzare
        for idx, row in enumerate(appointments, 1):
            appt = dict(zip(column_names, row))
            logger.info(f"Elaborazione appuntamento {idx}/{total} - ID {appt['appointment_id']}")
            # Se l'operatore non è mappato, salto
            if str(appt['operator_id']) not in self.operators:
                logger.error(f"Operatore non mappato: {appt['operator_id']}")
                continue
            # Preparo dati paziente
            patient_data = {
                'id': appt['patient_id'],
                'first_name': appt['first_name'],
                'last_name': appt['last_name'],
                'email': appt['email'],
                'primary_phone': appt['primary_phone'],
                'secondary_phone': appt['secondary_phone'],
                'gender': appt['gender'],
                'street': appt['street'],
                'city': appt['city'],
                'postcode': appt['postcode'],
                'province': appt['province'],
                'date_birth': appt['date_birth'],
                'place_of_birth': appt['place_of_birth'],
                'italian_fiscal_code': appt['italian_fiscal_code']
            }
            # Creo/aggiorno contatto
            contact_id = self._upsert_contact(patient_data)
            if not contact_id:
                continue
            # Scelgo il calendario giusto usando care_plan_code
            age = self._calculate_age(str(appt['date_birth']))
            care_code = appt.get('care_plan_code')
            cal_id = self._get_calendar_id(care_code, None, age)
            if not cal_id:
                continue
            # Creo o aggiorno l'appuntament
            self._create_or_update_appointment(appt, contact_id, cal_id)
        logger.info("Sincronizzazione appuntamenti completata")
        return True

    def sync_all_contacts(self):
        """
        Sincronizza tutti i contatti mancanti in GHL.
        """
        logger.info("Inizio sincronizzazione contatti mancanti...")
        patients = self.db.execute_query(
            "SELECT id, first_name, last_name, email, primary_phone, secondary_phone, gender, street, city, postcode, province, date_birth, place_of_birth, italian_fiscal_code FROM patients WHERE ghl_contact_id IS NULL ORDER BY id"
        )
        if not patients:
            logger.info("Nessun nuovo contatto da sincronizzare")
            return True
        total = len(patients)
        for idx, pat in enumerate(patients, 1):
            patient_data = {
                'id': pat[0], 'first_name': pat[1], 'last_name': pat[2],
                'email': pat[3], 'primary_phone': pat[4], 'secondary_phone': pat[5],
                'gender': pat[6], 'street': pat[7], 'city': pat[8], 'postcode': pat[9],
                'province': pat[10], 'date_birth': pat[11], 'place_of_birth': pat[12],
                'italian_fiscal_code': pat[13]
            }
            logger.info(f"[{idx}/{total}] Upsert contatto paziente {patient_data['id']}")
            self._upsert_contact(patient_data)
            time.sleep(1.5)
        logger.info("Sincronizzazione contatti completata")
        return True


def main():
    # Log di avvio centralizzato
    log_service_startup("ALFADOCS-GHL-SYNC")
    
    # Creo e avvio il servizio
    service = GHLSyncService()
    error_count = 0
    try:
        # Sincronizzazione appuntamenti (non bloccante)
        try:
            service.sync_appointments()
            logger.info("✅ Sincronizzazione appuntamenti completata")
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Errore sincronizzazione appuntamenti: {e}")
            logger.error(traceback.format_exc())
        
        # Sincronizzazione contatti (non bloccante)
        try:
            service.sync_all_contacts()
            logger.info("✅ Sincronizzazione contatti completata")
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Errore sincronizzazione contatti: {e}")
            logger.error(traceback.format_exc())
        
        # Riassunto finale
        if error_count == 0:
            logger.info("🎉 Sincronizzazione completata senza errori")
        else:
            logger.warning(f"⚠️ Sincronizzazione completata con {error_count} errori (vedi log)")
        
    except Exception as e:
        logger.error(f"💥 Errore critico generale: {e}")
        logger.error(traceback.format_exc())
        return 1
    finally:
        service.db.close()
    
    # Restituisci 0 anche se ci sono stati errori minori
    return 0

if __name__ == '__main__':
    sys.exit(main())