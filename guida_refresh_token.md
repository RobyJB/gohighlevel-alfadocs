# Guida all'endpoint `/oauth/refresh`

Questo endpoint serve a generare un nuovo **access token** quando quello corrente è scaduto, usando il **refresh token** salvato in precedenza nel database.

## URL e Metodo
POST https://crm.abitarerea.com/oauth/refresh

## Autenticazione
// Non è più necessario inviare l'header Authorization, ora l'endpoint è pubblico e accessibile senza token.

## Parametri
Il corpo della richiesta deve essere JSON e contenere uno dei seguenti campi:
- `location_id`: ID della location (per token di tipo "Location")
- `company_id`: ID della company  (per token di tipo "Company")

### Esempio di body JSON
```json
{ "location_id": "KtQ7QU1mxRijW7rBoCxP" }
```
// Qui ho inserito il nostro location_id come esempio pratico.

## Funzionamento interno
1. Estrae dal DB il `refresh_token` corrispondente a `location_id` o `company_id`.
2. Fa la richiesta POST a GoHighLevel con `grant_type=refresh_token` per ottenere nuovi token.
3. Aggiorna la tabella `oauth_tokens` con il nuovo `access_token`, `refresh_token` e `expires_in`.
4. Ritorna al chiamante il nuovo access token in formato JSON.

## Esempio di richiesta (curl)
```bash
# Rigenera il token per la nostra location
curl -X POST https://crm.abitarerea.com/oauth/refresh \
  -H "Content-Type: application/json" \
  -d '{"location_id":"KtQ7QU1mxRijW7rBoCxP"}'
```
// In questo esempio puoi copiare direttamente il comando per usarlo in altri progetti.

## Esempio di risposta (200 OK)
```json
{
  "access_token": "nuovo_access_token_valido"
}
```

## Esempi di errori comuni

### 1. Body JSON mancante
```http
HTTP/1.1 400 Bad Request
Content-Type: application/json

{"error":"Body JSON mancante"}
```

### 2. Parametri obbligatori mancanti
```http
HTTP/1.1 400 Bad Request
Content-Type: application/json

{"error":"Parametri obbligatori: location_id o company_id"}
```

### 3. Errore nella richiesta a GoHighLevel
```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{"error":"Errore nella richiesta a GHL"}
```

### 4. Errore di database durante il refresh
```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{"error":"Errore DB durante il refresh"}
```

### 5. Errore interno al server
```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{"error":"Errore interno del server"}
```
