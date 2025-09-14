#!/usr/bin/env python3
# Carica le variabili d'ambiente dal file .env
from dotenv import load_dotenv
load_dotenv()

import requests
import logging
import os
import time
from datetime import datetime
import hashlib
import json
from typing import Dict, List, Optional

# Configurazione del logger (info su file e console)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/alfadocs_patients_sync.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Importo il DatabaseManager dal servizio careplan
from alfadocs_careplan_sync import DatabaseManager

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

class AlfaDocsPatientsSync:
    def __init__(self):
        # Configurazione API AlfaDocs dal file .env
        self.API_KEY = os.getenv('ALFADOCS_API_KEY')
        self.PRACTICE_ID = os.getenv('ALFADOCS_PRACTICE_ID')
        self.ARCHIVE_ID = os.getenv('ALFADOCS_ARCHIVE_ID')
        self.BASE_URL = os.getenv('ALFADOCS_BASE_URL')
        # Normalizzo BASE_URL per rimuovere slash finale
        self.BASE_URL = self.BASE_URL.rstrip('/')
        # Verifica credenziali
        if not all([self.API_KEY, self.PRACTICE_ID, self.ARCHIVE_ID, self.BASE_URL]):
            raise ValueError("❌ Credenziali AlfaDocs mancanti nel file .env")
        self.headers = {"X-Api-Key": self.API_KEY}
        
        # Setup logger e database
        self.logger = logging.getLogger(__name__)
        self.db = DatabaseManager(self.logger)
        
        # Statistiche sincronizzazione
        self.stats = {
            'total_patients_found': 0,
            'new_patients_added': 0,
            'patients_updated': 0,
            'errors': 0,
            'start_time': datetime.now()
        }

    def calculate_hash(self, data: Dict) -> str:
        """Calcola un hash dei dati per rilevare modifiche"""
        return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def process_patients_page(self, patients: List[Dict], page_num: int, total_pages: int) -> None:
        """Processa una pagina di pazienti e li salva nel database"""
        page_stats = {
            'new': 0,
            'updated': 0,
            'errors': 0
        }
        
        self.logger.info(f"📄 Processando pagina {page_num}/{total_pages} ({len(patients)} pazienti)")
        
        for idx, patient in enumerate(patients, 1):
            try:
                self.logger.info(f"🔄 Processando paziente {idx}/{len(patients)}: {patient.get('firstName')} {patient.get('lastName')} (ID: {patient.get('id')})")
                
                if self.save_or_update_patient(patient):
                    if not self.db.execute_query("SELECT hash_value FROM patients WHERE id = %s", (patient['id'],))[0][0]:
                        page_stats['new'] += 1
                        self.stats['new_patients_added'] += 1
                    else:
                        page_stats['updated'] += 1
                        self.stats['patients_updated'] += 1
                else:
                    page_stats['errors'] += 1
                    self.stats['errors'] += 1
                    
            except Exception as e:
                self.logger.error(f"❌ Errore processando paziente {patient.get('id')}: {e}")
                page_stats['errors'] += 1
                self.stats['errors'] += 1
                continue
        
        self.logger.info(f"""
📊 Statistiche pagina {page_num}/{total_pages}:
   - Nuovi: {page_stats['new']}
   - Aggiornati: {page_stats['updated']}
   - Errori: {page_stats['errors']}
""")

    def fetch_patients(self) -> bool:
        """Recupera tutti i pazienti da AlfaDocs e li processa pagina per pagina"""
        endpoint = f"{self.BASE_URL}/v1/practices/{self.PRACTICE_ID}/archives/{self.ARCHIVE_ID}/patients"
        current_page = 1
        total_patients = 0

        self.logger.info("🚀 Inizio recupero pazienti da AlfaDocs")
        self.logger.info(f"📡 Endpoint iniziale: {endpoint}")
        
        try:
            while True:
                self.logger.info(f"📄 Recupero pagina {current_page}...")
                response = requests.get(endpoint, headers=self.headers, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                patients = data.get('results', [])
                if not patients:
                    if current_page == 1:
                        self.logger.error("❌ Nessun paziente recuperato da AlfaDocs")
                        return False
                    break
                
                total_patients += len(patients)
                self.logger.info(f"📊 Processati {total_patients} pazienti finora")
                
                # Processa la pagina corrente
                self.process_patients_page(patients, current_page, data.get('links', {}).get('pages', 1))
                
                # Controlla se c'è una prossima pagina
                next_page = data.get('links', {}).get('next')
                if not next_page:
                    break
                    
                endpoint = next_page
                current_page += 1
            
            self.stats['total_patients_found'] = total_patients
            self.logger.info(f"📊 Totale pazienti processati: {total_patients}")
            return True
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"❌ Errore recupero pazienti: {e}")
            return False
        except Exception as e:
            self.logger.error(f"❌ Errore inaspettato recupero pazienti: {e}")
            return False

    def save_or_update_patient(self, patient_data: Dict) -> bool:
        """Salva o aggiorna un paziente nel database"""
        try:
            sanitized_data = patient_data.copy()
            
            # Gestione data di nascita
            date_birth = sanitized_data.get('dateBirth')
            if date_birth and date_birth.startswith('-'):
                date_birth = None
            
            # Gestione codice fiscale
            fiscal_code = sanitized_data.get('italianFiscalCode')
            if fiscal_code in ['NON DISPONIBILE', '', None]:
                fiscal_code = None
                
            # Calcola hash per verificare modifiche
            current_hash = self.calculate_hash(sanitized_data)
            
            # Verifica se il paziente esiste e se è cambiato
            result = self.db.execute_query(
                "SELECT hash_value, ghl_contact_id FROM patients WHERE id = %s", 
                (sanitized_data['id'],)
            )
            
            old_hash = result[0][0] if result else None
            ghl_contact_id = result[0][1] if result else None
            
            # Se l'hash è uguale, non serve aggiornare
            if old_hash == current_hash:
                return True
                
            # Prepara i numeri di telefono
            phone_numbers = sanitized_data.pop('phoneNumbers', [])
            primary_phone = None
            secondary_phone = None
            
            if len(phone_numbers) > 0:
                primary_phone = f"{phone_numbers[0].get('prefix', '')}{phone_numbers[0].get('number', '')}"
            if len(phone_numbers) > 1:
                secondary_phone = f"{phone_numbers[1].get('prefix', '')}{phone_numbers[1].get('number', '')}"
            
            # Prepara i dati per il database
            patient_db_data = {
                'id': sanitized_data['id'],
                'first_name': sanitized_data.get('firstName', ''),
                'last_name': sanitized_data.get('lastName', ''),
                'email': sanitized_data.get('email', ''),
                'email_enabled': sanitized_data.get('emailEnabled', False),
                'email_valid': sanitized_data.get('emailValid', False),
                'primary_phone': primary_phone,
                'secondary_phone': secondary_phone,
                'gender': sanitized_data.get('gender', ''),
                'street': sanitized_data.get('street', ''),
                'city': sanitized_data.get('city', ''),
                'postcode': sanitized_data.get('postcode', ''),
                'province': sanitized_data.get('province', ''),
                'date_birth': date_birth,
                'place_of_birth': sanitized_data.get('placeOfBirth', ''),
                'italian_fiscal_code': fiscal_code,
                'job': sanitized_data.get('job', ''),
                'yearly_numbering_year': sanitized_data.get('yearlyNumberingYear'),
                'yearly_numbering_number': sanitized_data.get('yearlyNumberingNumber'),
                'default_discount': sanitized_data.get('defaultDiscount', 0),
                'source_id': sanitized_data.get('sourceId'),
                'price_list_id': sanitized_data.get('priceListId'),
                'email_reminder_possible': sanitized_data.get('emailReminderPossible', False),
                'sms_reminder_possible': sanitized_data.get('smsReminderPossible', False),
                'created_at': sanitized_data.get('createdAt'),
                'document_signature_email_possible': sanitized_data.get('documentSignatureEmailPossible', False),
                'last_modified_at': sanitized_data.get('lastModifiedAt'),
                'hash_value': current_hash,
                'last_synced_at': datetime.now(),
                'ghl_contact_id': ghl_contact_id,
                'needs_sync': True  # Marca per sincronizzazione GHL
            }
            
            # Log dettagliato
            self.logger.info(f"""
📝 Dati paziente da salvare:
   - ID: {patient_db_data['id']}
   - Nome: {patient_db_data['first_name']} {patient_db_data['last_name']}
   - Email: {patient_db_data['email']}
   - Telefono: {patient_db_data['primary_phone']}
   - Codice Fiscale: {patient_db_data['italian_fiscal_code']}
   - GHL Contact ID: {patient_db_data['ghl_contact_id']}
   - Hash: {current_hash}
   - Vecchio Hash: {old_hash}
""")
            
            # Query per inserire o aggiornare
            query = """
                INSERT INTO patients (
                    id, first_name, last_name, email, email_enabled, email_valid,
                    primary_phone, secondary_phone, gender, street, city, postcode,
                    province, date_birth, place_of_birth, italian_fiscal_code, job,
                    yearly_numbering_year, yearly_numbering_number, default_discount,
                    source_id, price_list_id, email_reminder_possible, sms_reminder_possible,
                    created_at, document_signature_email_possible, last_modified_at,
                    hash_value, last_synced_at, ghl_contact_id, needs_sync
                ) VALUES (
                    %(id)s, %(first_name)s, %(last_name)s, %(email)s, %(email_enabled)s,
                    %(email_valid)s, %(primary_phone)s, %(secondary_phone)s, %(gender)s,
                    %(street)s, %(city)s, %(postcode)s, %(province)s, %(date_birth)s,
                    %(place_of_birth)s, %(italian_fiscal_code)s, %(job)s,
                    %(yearly_numbering_year)s, %(yearly_numbering_number)s, %(default_discount)s,
                    %(source_id)s, %(price_list_id)s, %(email_reminder_possible)s,
                    %(sms_reminder_possible)s, %(created_at)s, %(document_signature_email_possible)s,
                    %(last_modified_at)s, %(hash_value)s, %(last_synced_at)s,
                    %(ghl_contact_id)s, %(needs_sync)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    email = EXCLUDED.email,
                    email_enabled = EXCLUDED.email_enabled,
                    email_valid = EXCLUDED.email_valid,
                    primary_phone = EXCLUDED.primary_phone,
                    secondary_phone = EXCLUDED.secondary_phone,
                    gender = EXCLUDED.gender,
                    street = EXCLUDED.street,
                    city = EXCLUDED.city,
                    postcode = EXCLUDED.postcode,
                    province = EXCLUDED.province,
                    date_birth = EXCLUDED.date_birth,
                    place_of_birth = EXCLUDED.place_of_birth,
                    italian_fiscal_code = EXCLUDED.italian_fiscal_code,
                    job = EXCLUDED.job,
                    yearly_numbering_year = EXCLUDED.yearly_numbering_year,
                    yearly_numbering_number = EXCLUDED.yearly_numbering_number,
                    default_discount = EXCLUDED.default_discount,
                    source_id = EXCLUDED.source_id,
                    price_list_id = EXCLUDED.price_list_id,
                    email_reminder_possible = EXCLUDED.email_reminder_possible,
                    sms_reminder_possible = EXCLUDED.sms_reminder_possible,
                    document_signature_email_possible = EXCLUDED.document_signature_email_possible,
                    last_modified_at = EXCLUDED.last_modified_at,
                    hash_value = EXCLUDED.hash_value,
                    last_synced_at = EXCLUDED.last_synced_at,
                    needs_sync = EXCLUDED.needs_sync
                RETURNING id, first_name, last_name, needs_sync
            """
            
            result = self.db.execute_query(query, patient_db_data)
            
            if result:
                self.logger.info(f"✅ Paziente salvato/aggiornato: {result[0][1]} {result[0][2]} (ID: {result[0][0]})")
                if not old_hash:
                    self.stats['new_patients_added'] += 1
                else:
                    self.stats['patients_updated'] += 1
                return True
            else:
                self.logger.warning(f"⚠️ Errore salvataggio paziente {patient_data.get('id')}")
                self.stats['errors'] += 1
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Errore aggiornamento paziente {patient_data.get('id')}: {e}")
            self.stats['errors'] += 1
            return False

    def sync_patients(self):
        """Funzione principale di sincronizzazione pazienti"""
        try:
            self.logger.info("🚀 Inizio sincronizzazione pazienti")
            
            # Recupera e processa i pazienti pagina per pagina
            if not self.fetch_patients():
                self.logger.error("❌ Errore durante il recupero dei pazienti")
                return False
            
            # Log finale
            duration = datetime.now() - self.stats['start_time']
            self.logger.info(f"""
🎉 Sincronizzazione completata!
📊 Statistiche finali:
   - Totale pazienti trovati: {self.stats['total_patients_found']}
   - Nuovi pazienti aggiunti: {self.stats['new_patients_added']}
   - Pazienti aggiornati: {self.stats['patients_updated']}
   - Errori: {self.stats['errors']}
   - Durata: {duration}
""")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Errore durante la sincronizzazione: {e}")
            return False
        finally:
            self.db.close()

def main():
    """Funzione principale con gestione exit code"""
    import sys
    
    # Log di avvio centralizzato
    log_service_startup("ALFADOCS-PATIENTS-SYNC")
    
    try:
        sync_service = AlfaDocsPatientsSync()
        success = sync_service.sync_patients()
        
        if success:
            print("✅ Sincronizzazione completata con successo")
            sys.exit(0)  # Exit code 0 = successo
        else:
            print("❌ Sincronizzazione fallita")
            sys.exit(1)  # Exit code 1 = errore
            
    except Exception as e:
        print(f"❌ Errore fatale: {e}")
        sys.exit(1)  # Exit code 1 = errore
    except KeyboardInterrupt:
        print("⚠️ Sincronizzazione interrotta dall'utente")
        sys.exit(130)  # Exit code standard per SIGINT

if __name__ == '__main__':
    main() 