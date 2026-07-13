#!/usr/bin/env python3
"""
Obtener el refresh token de Gmail (ejecutar UNA sola vez, en tu computadora)
===========================================================================

Sirve para autorizar el envío de correos desde aceptados.cursos@gmail.com sin
guardar una contraseña. Genera un "refresh token" que luego se guarda como
secreto de GitHub Actions.

Pasos:

1. En Google Cloud Console (mismo proyecto de la cuenta de servicio):
   - Habilita la "Gmail API".
   - Pantalla de consentimiento OAuth: tipo "Externo"; agrega el scope
     .../auth/gmail.send; agrega aceptados.cursos@gmail.com como usuario de
     prueba y, para que el token NO caduque, cambia el estado a "En producción".
   - Crea credenciales → "ID de cliente de OAuth" → tipo "App de escritorio".
   - Descarga el JSON y guárdalo junto a este archivo como  client_secret.json

2. Instala la librería del flujo (solo local):
       pip install google-auth-oauthlib

3. Ejecuta:
       python get_gmail_token.py
   Se abrirá el navegador: inicia sesión con aceptados.cursos@gmail.com y acepta.

4. Copia los tres valores que imprime y guárdalos como secretos del repo:
       GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    # access_type=offline + prompt=consent asegura que Google entregue refresh_token.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    print("\n===== Guarda estos valores como secretos de GitHub =====\n")
    print(f"GMAIL_CLIENT_ID     = {creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET = {creds.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN = {creds.refresh_token}")
    if not creds.refresh_token:
        print(
            "\n[aviso] No se recibió refresh_token. Ve a "
            "https://myaccount.google.com/permissions, revoca el acceso de la "
            "app y vuelve a ejecutar este script."
        )


if __name__ == "__main__":
    main()
