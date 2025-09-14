-- Migrazione: Aumenta dimensione campo italian_fiscal_code
-- Data: 2025-07-01
-- Problema: Errore "value too long for type character varying(16)" 
-- Causa: Campo italian_fiscal_code troppo piccolo (16 caratteri) per alcuni valori (es. 20 zeri)

-- Aumenta la dimensione del campo italian_fiscal_code da VARCHAR(16) a VARCHAR(32)
-- Questo permetterà di gestire codici fiscali standard (16 caratteri) e valori di test più lunghi

ALTER TABLE patients 
ALTER COLUMN italian_fiscal_code TYPE VARCHAR(32);

-- Verifica che la modifica sia stata applicata
SELECT column_name, data_type, character_maximum_length 
FROM information_schema.columns 
WHERE table_name = 'patients' 
  AND column_name = 'italian_fiscal_code';

-- Messaggio di conferma
SELECT 'Campo italian_fiscal_code aggiornato con successo a VARCHAR(32)' as risultato; 