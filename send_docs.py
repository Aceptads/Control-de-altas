#!/usr/bin/env python3
"""
Envío de la documentación de inscripción por Gmail (OAuth)
==========================================================

Envía, desde aceptados.cursos@gmail.com, el correo de "Documentos Inscripción"
con los tres formatos adjuntos (FO-04, FO-02, FO-03) al correo del alumno.

Autenticación: OAuth de usuario. En vez de una contraseña, se usa un
*refresh token* generado una sola vez (ver get_gmail_token.py) y guardado como
secreto de GitHub Actions junto con el client_id/secret de la app de OAuth:

    GMAIL_CLIENT_ID
    GMAIL_CLIENT_SECRET
    GMAIL_REFRESH_TOKEN

El asunto y el cuerpo salen de los archivos de la carpeta plantilla/ para que
se puedan editar sin tocar el código. Ambos admiten el marcador {nombre}.
"""

from __future__ import annotations

import base64
import os
from email.message import EmailMessage

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "aceptados.cursos@gmail.com")
GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

_HERE = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(_HERE, "docs")
PLANTILLA_DIR = os.path.join(_HERE, "plantilla")

# Adjuntos que se envían con cada alta (deben existir en docs/).
ATTACHMENTS = [
    "FO-04 Carta Compromiso Rev.02.pdf",
    "FO-02 Reglamento Rev.02.pdf",
    "FO-03 Políticas Rev.02.pdf",
]


def build_gmail_service():
    """Devuelve el cliente de Gmail o None si faltan credenciales."""
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=GMAIL_TOKEN_URI,
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def load_template(nombre: str = "") -> tuple[str, str]:
    """Lee asunto (texto) y cuerpo (HTML) de la carpeta plantilla/.

    Sustituye el marcador {nombre} por el nombre del alumno (o cadena vacía).
    """
    asunto = _read(os.path.join(PLANTILLA_DIR, "asunto.txt")).strip()
    cuerpo = _read(os.path.join(PLANTILLA_DIR, "cuerpo.html"))
    asunto = asunto.replace("{nombre}", nombre or "")
    cuerpo = cuerpo.replace("{nombre}", nombre or "")
    return asunto, cuerpo


def build_message(to_email: str, nombre: str = "") -> EmailMessage:
    asunto, cuerpo_html = load_template(nombre)

    msg = EmailMessage()
    msg["To"] = to_email
    msg["From"] = GMAIL_SENDER
    msg["Subject"] = asunto
    msg.set_content(
        "Adjuntamos la documentación de inscripción de Aceptados. "
        "Si no ves el contenido, abre este correo en un cliente compatible con HTML."
    )
    msg.add_alternative(cuerpo_html, subtype="html")

    for fname in ATTACHMENTS:
        path = os.path.join(DOCS_DIR, fname)
        with open(path, "rb") as fh:
            data = fh.read()
        msg.add_attachment(
            data, maintype="application", subtype="pdf", filename=fname
        )
    return msg


def send_docs(service, to_email: str, nombre: str = "") -> str:
    """Envía el correo con adjuntos. Devuelve el id del mensaje enviado."""
    msg = build_message(to_email, nombre)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent.get("id", "")
