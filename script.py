#!/usr/bin/env python3
"""
Script per recuperare i dati completi di un appuntamento e del care plan associato (se presente)
"""

import os
import json
import logging
import requests
import time
from datetime import datetime
from dotenv import load_dotenv
import argparse


def setup_logging():
    """
    Configura il logger per scrivere su file condiviso e su console
    """
    log_file = 'alfadocs_sync.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


def log_separator(logger, script_name):
    """
    Inserisce un separatore nel log per segnare l'inizio dello script
    """
    logger.info("=" * 80)
    logger.info(f"SCRIPT: {script_name}")
    logger.info(f"AVVIO: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)


def load_config():
    """
    Carica le credenziali dal file .env e restituisce il dizionario di configurazione
    """
    load_dotenv('.env')
    config = {
        'api_key': os.getenv('ALFADOCS_API_KEY'),
        'practice_id': os.getenv('ALFADOCS_PRACTICE_ID'),
        'archive_id': os.getenv('ALFADOCS_ARCHIVE_ID'),
        'base_url': os.getenv('ALFADOCS_BASE_URL')
    }
    missing = [k for k,v in config.items() if not v]
    if missing:
        raise ValueError(f"Credenziali mancanti nel file .env: {missing}")
    return config


def get_appointment_details(appointment_id, config, logger):
    """
    Recupera i dettagli di un singolo appuntamento tramite API
    """
    url = f"{config['base_url']}/v1/practices/{config['practice_id']}/archives/{config['archive_id']}/appointments/{appointment_id}"
    headers = {'X-Api-Key': config['api_key'], 'Content-Type': 'application/json'}
    try:
        logger.info(f"GET_APPOINTMENT | Recupero dettagli appuntamento ID: {appointment_id}")
        response = requests.get(url, headers=headers, timeout=30)
        logger.info(f"GET_APPOINTMENT | Codice risposta HTTP: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            logger.info(f"GET_APPOINTMENT | ✅ Appuntamento {appointment_id} recuperato")
            return data
        else:
            logger.error(f"GET_APPOINTMENT | Errore API {response.status_code}: {response.text}")
            return None
    except Exception as e:
        logger.error(f"GET_APPOINTMENT | Eccezione: {e}")
        return None


def get_care_plan_details(care_plan_id, config, logger):
    """
    Recupera i dettagli completi di un care plan tramite API
    """
    url = f"{config['base_url']}/v1/practices/{config['practice_id']}/archives/{config['archive_id']}/care-plans/{care_plan_id}"
    headers = {'X-Api-Key': config['api_key'], 'Content-Type': 'application/json'}
    try:
        logger.info(f"GET_CAREPLAN | Recupero dettagli Care Plan ID: {care_plan_id}")
        response = requests.get(url, headers=headers, timeout=30)
        logger.info(f"GET_CAREPLAN | Codice risposta HTTP: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            logger.info(f"GET_CAREPLAN | ✅ Care Plan {care_plan_id} recuperato")
            return {'success': True, 'data': data}
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            logger.error(f"GET_CAREPLAN | Errore API {error_msg}")
            return {'success': False, 'error_code': response.status_code, 'error_msg': response.text}
    except Exception as e:
        logger.error(f"GET_CAREPLAN | Eccezione: {e}")
        return {'success': False, 'error_code': 'EXCEPTION', 'error_msg': str(e)}


def get_care_plan_signature_status(care_plan_id, config, logger):
    """
    Recupera lo stato della firma di un care plan (se presente)
    """
    url = f"{config['base_url']}/v1/practices/{config['practice_id']}/archives/{config['archive_id']}/care-plans/{care_plan_id}/signature-status"
    headers = {'X-Api-Key': config['api_key'], 'Content-Type': 'application/json'}
    try:
        logger.info(f"GET_SIGNATURE | Recupero stato firma Care Plan ID: {care_plan_id}")
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            logger.info(f"GET_SIGNATURE | ✅ Stato firma recuperato")
            return data
        else:
            logger.warning(f"GET_SIGNATURE | Stato firma non disponibile (HTTP {response.status_code})")
            return None
    except Exception as e:
        logger.error(f"GET_SIGNATURE | Eccezione: {e}")
        return None


def main():
    """
    Funzione principale: gestisce parsing argomento, recupera e mostra dati
    """
    logger = setup_logging()
    log_separator(logger, "GET_APPOINTMENT_CAREPLAN v1.0")
    parser = argparse.ArgumentParser(description="Recupera dati appuntamento e care plan associato")
    parser.add_argument("-a", "--appointment-id", help="ID dell'appuntamento", required=True)
    args = parser.parse_args()
    appointment_id = args.appointment_id

    try:
        config = load_config()
        # Dettagli appuntamento
        details = get_appointment_details(appointment_id, config, logger)
        if details and 'data' in details:
            logger.info("MAIN | === DATI APPUNTAMENTO ===")
            logger.info(json.dumps(details['data'], indent=2, ensure_ascii=False))
            # Cerca care plan associato
            care_plan_id = details['data'].get('carePlanId')
            if care_plan_id and care_plan_id != 'N/A':
                logger.info(f"MAIN | 🗂️ Care Plan associato: {care_plan_id}")
                cp_result = get_care_plan_details(care_plan_id, config, logger)
                if cp_result['success'] and 'data' in cp_result:
                    logger.info("MAIN | === DATI CARE PLAN ===")
                    logger.info(json.dumps(cp_result['data']['data'], indent=2, ensure_ascii=False))
                    sig = get_care_plan_signature_status(care_plan_id, config, logger)
                    if sig and 'data' in sig:
                        logger.info("MAIN | === STATO FIRMA ===")
                        logger.info(json.dumps(sig['data'], indent=2, ensure_ascii=False))
                else:
                    # Analisi dettagliata dell'errore
                    if cp_result['error_code'] == 404:
                        logger.warning(f"MAIN | ⚠️ Care Plan {care_plan_id} NON ESISTE PIÙ (HTTP 404) - Potrebbe essere stato eliminato")
                    elif cp_result['error_code'] == 403:
                        logger.warning(f"MAIN | ⚠️ Care Plan {care_plan_id} NON ACCESSIBILE - PERMESSI INSUFFICIENTI (HTTP 403)")
                    elif cp_result['error_code'] == 400:
                        logger.warning(f"MAIN | ⚠️ Care Plan {care_plan_id} RICHIESTA NON VALIDA (HTTP 400) - {cp_result['error_msg']}")
                    else:
                        logger.warning(f"MAIN | ⚠️ Care Plan {care_plan_id} ERRORE SCONOSCIUTO (HTTP {cp_result['error_code']}) - {cp_result['error_msg']}")
        else:
            logger.error(f"MAIN | ❌ Appuntamento {appointment_id} non trovato")
    except Exception as e:
        logger.error(f"MAIN | Errore: {e}")
    finally:
        logger.info("MAIN | Fine esecuzione")


if __name__ == "__main__":
    main() 