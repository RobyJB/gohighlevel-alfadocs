# Migrazioni Database AlfaDocs

Questa cartella contiene i file di migrazione SQL per aggiornare lo schema del database.

## Come eseguire le migrazioni

### 1. Accesso al database
Prima devi connetterti al database PostgreSQL:

```bash
# Se usi docker-compose
docker-compose exec postgres psql -U [username] -d [database_name]

# Oppure se hai PostgreSQL locale
psql -U [username] -d [database_name] -h [host]
```

### 2. Eseguire una migrazione
Copia e incolla il contenuto del file SQL nel prompt di PostgreSQL:

```sql
\i migrations/001_fix_italian_fiscal_code_length.sql
```

Oppure esegui direttamente:

```bash
psql -U [username] -d [database_name] -f migrations/001_fix_italian_fiscal_code_length.sql
```

## Lista Migrazioni

- **001_fix_italian_fiscal_code_length.sql** - Aumenta dimensione campo `italian_fiscal_code` da VARCHAR(16) a VARCHAR(32)
  - **Problema risolto:** Errore "value too long for type character varying(16)"
  - **Data:** 2025-07-01

## Note Importanti

- **Sempre fare backup** del database prima di eseguire migrazioni
- Eseguire le migrazioni in **ordine numerico** (001, 002, 003, ecc.)
- Testare prima in ambiente di sviluppo
- Le migrazioni vanno eseguite **prima** di riavviare le sincronizzazioni 