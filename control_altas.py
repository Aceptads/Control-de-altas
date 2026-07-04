#!/usr/bin/env python3
"""
Control de altas — Aceptados
============================

Para cada fila de la hoja "Altas" (Nombre en A, Correo de contacto en C,
Costo en F, Meses en G) busca la respuesta correspondiente en el Google Form
y completa:

    D  Especialidad   -> respuesta a "CARRERA O LICENCIATURA A LA QUE DESEA INGRESAR"
    E  Curso          -> primera palabra de "CURSO QUE DESEA TOMAR" (p.ej. "UNAM")
    H  Mensualidad     -> Costo (F) / Meses (G)

El emparejamiento exige coincidencia EXACTA del correo (columna C == pregunta
"CORREO DEL ALUMNO") y usa similitud difusa del nombre (tolera acentos y el
orden apellido/nombre) para desempatar cuando un mismo correo tiene varias
respuestas. El nombre de la hoja se compara contra "NOMBRE COMPLETO DEL ALUMNO"
y "NOMBRE DEL PADRE O TUTOR", tomando el mejor de los dos.

Autenticación: cuenta de servicio de Google cuyo JSON se pasa por la variable
de entorno GOOGLE_SERVICE_ACCOUNT_JSON (secreto de GitHub Actions).
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

from google.oauth2 import service_account
from googleapiclient.discovery import build
from rapidfuzz import fuzz

# --------------------------------------------------------------------------- #
# Configuración (los valores por defecto se pueden sobreescribir por entorno)  #
# --------------------------------------------------------------------------- #
SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "10mn2MK2ipBTpbcVm2wl4lUVfHt-WXuTFRoM88dxEUuc"
)
FORM_ID = os.environ.get("FORM_ID", "1m5UruvwSlDdvGrMqKnrMQs3ptN1lLgD51sIGA7wHfUA")
SHEET_NAME = os.environ.get("SHEET_NAME", "Altas")

# Número de filas de encabezado antes de que empiecen los datos.
HEADER_ROWS = int(os.environ.get("HEADER_ROWS", "1"))

# Si es "true", sobrescribe celdas que ya tengan contenido. Por defecto solo
# rellena celdas vacías (no pisa correcciones manuales).
OVERWRITE = os.environ.get("OVERWRITE", "false").lower() == "true"

# Si es "true", muestra lo que haría pero no escribe en la hoja.
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# Umbral (0-100) de similitud de nombre para reportar un emparejamiento como
# dudoso en el log (no bloquea; el correo exacto manda).
NAME_WARN_THRESHOLD = int(os.environ.get("NAME_WARN_THRESHOLD", "60"))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/forms.body.readonly",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]

# Títulos de las preguntas del formulario (se comparan de forma tolerante).
Q_EMAIL = "CORREO DEL ALUMNO"
Q_NAME_STUDENT = "NOMBRE COMPLETO DEL ALUMNO"
Q_NAME_TUTOR = "NOMBRE DEL PADRE O TUTOR"
Q_CARRERA = "CARRERA O LICENCIATURA A LA QUE DESEA INGRESAR"
Q_CURSO = "CURSO QUE DESEA TOMAR"


# --------------------------------------------------------------------------- #
# Utilidades de normalización                                                  #
# --------------------------------------------------------------------------- #
def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def norm_title(text: str) -> str:
    """Normaliza el título de una pregunta para compararlo de forma tolerante."""
    text = strip_accents(text or "").upper()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def norm_email(text: str) -> str:
    return (text or "").strip().lower()


def norm_name(text: str) -> str:
    text = strip_accents(text or "").lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def name_similarity(a: str, b: str) -> float:
    """0-100. token_sort_ratio ignora el orden de las palabras (apellido/nombre)."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    return fuzz.token_sort_ratio(na, nb)


def first_word(text: str) -> str:
    text = (text or "").strip()
    return text.split()[0] if text else ""


def parse_number(value) -> float | None:
    """Convierte '$5,000.00', '5000', '4' -> float. Devuelve None si no se puede."""
    if value is None:
        return None
    s = re.sub(r"[^0-9.,-]", "", str(value).strip())
    s = s.replace(",", "")  # se asume ',' separador de miles, '.' decimal (formato MX)
    if s in ("", "-", ".", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Credenciales y clientes                                                      #
# --------------------------------------------------------------------------- #
def build_services():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        sys.exit(
            "ERROR: falta la variable de entorno GOOGLE_SERVICE_ACCOUNT_JSON "
            "(el JSON de la cuenta de servicio)."
        )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: GOOGLE_SERVICE_ACCOUNT_JSON no es un JSON válido: {exc}")

    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    forms = build("forms", "v1", credentials=creds, static_discovery=False,
                  cache_discovery=False)
    return sheets, forms


# --------------------------------------------------------------------------- #
# Lectura del formulario                                                       #
# --------------------------------------------------------------------------- #
def load_form_records(forms) -> list[dict]:
    form = forms.forms().get(formId=FORM_ID).execute()

    title_to_qid: dict[str, str] = {}
    for item in form.get("items", []):
        question = item.get("questionItem", {}).get("question")
        if question and "questionId" in question:
            title_to_qid[norm_title(item.get("title", ""))] = question["questionId"]

    def find_qid(target: str) -> str | None:
        nt = norm_title(target)
        if nt in title_to_qid:
            return title_to_qid[nt]
        for title, qid in title_to_qid.items():
            if nt in title or title in nt:
                return qid
        return None

    qid_email = find_qid(Q_EMAIL)
    qid_name_student = find_qid(Q_NAME_STUDENT)
    qid_name_tutor = find_qid(Q_NAME_TUTOR)
    qid_carrera = find_qid(Q_CARRERA)
    qid_curso = find_qid(Q_CURSO)

    for label, qid in [
        (Q_EMAIL, qid_email),
        (Q_NAME_STUDENT, qid_name_student),
        (Q_NAME_TUTOR, qid_name_tutor),
        (Q_CARRERA, qid_carrera),
        (Q_CURSO, qid_curso),
    ]:
        if qid is None:
            print(f"  [aviso] No se encontró la pregunta: «{label}»")

    def values_of(response: dict, qid: str | None) -> list[str]:
        if not qid:
            return []
        answer = response.get("answers", {}).get(qid)
        if not answer:
            return []
        return [a.get("value", "") for a in answer.get("textAnswers", {}).get("answers", [])]

    def first_value(response: dict, qid: str | None) -> str:
        vals = values_of(response, qid)
        return vals[0] if vals else ""

    # Traer todas las respuestas (con paginación).
    responses: list[dict] = []
    page_token = None
    while True:
        resp = (
            forms.forms()
            .responses()
            .list(formId=FORM_ID, pageToken=page_token)
            .execute()
        )
        responses.extend(resp.get("responses", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    records = []
    for r in responses:
        records.append(
            {
                "email": norm_email(first_value(r, qid_email)),
                "email_raw": first_value(r, qid_email),
                "name_student": first_value(r, qid_name_student),
                "name_tutor": first_value(r, qid_name_tutor),
                "carrera": first_value(r, qid_carrera),
                "curso_values": values_of(r, qid_curso),
                "create_time": r.get("createTime", ""),
            }
        )
    return records


# --------------------------------------------------------------------------- #
# Emparejamiento                                                               #
# --------------------------------------------------------------------------- #
def best_match(name: str, email: str, records: list[dict]) -> tuple[dict | None, float]:
    """Correo exacto obligatorio; el nombre difuso desempata y da confianza."""
    email = norm_email(email)
    if not email:
        return None, 0.0

    candidates = [rec for rec in records if rec["email"] and rec["email"] == email]
    if not candidates:
        return None, 0.0

    def score(rec: dict) -> float:
        return max(
            name_similarity(name, rec["name_student"]),
            name_similarity(name, rec["name_tutor"]),
        )

    candidates.sort(key=lambda rec: (score(rec), rec["create_time"]), reverse=True)
    best = candidates[0]
    return best, score(best)


# --------------------------------------------------------------------------- #
# Proceso principal                                                            #
# --------------------------------------------------------------------------- #
def cell(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) and row[index] is not None else ""


def main() -> None:
    print("== Control de altas ==")
    print(f"  Hoja: {SHEET_NAME}  |  Overwrite: {OVERWRITE}  |  Dry-run: {DRY_RUN}")

    sheets, forms = build_services()

    print("Leyendo respuestas del formulario...")
    records = load_form_records(forms)
    print(f"  {len(records)} respuestas cargadas.")

    print("Leyendo hoja Altas...")
    read_range = f"'{SHEET_NAME}'!A1:J"
    result = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=read_range)
        .execute()
    )
    rows = result.get("values", [])
    data_rows = rows[HEADER_ROWS:]
    print(f"  {len(data_rows)} filas de datos.")

    updates: list[dict] = []
    n_matched = 0
    n_not_found = 0

    for i, row in enumerate(data_rows):
        sheet_row = HEADER_ROWS + 1 + i
        nombre = cell(row, 0)  # A
        correo = cell(row, 2)  # C
        costo = cell(row, 5)   # F
        meses = cell(row, 6)   # G

        if not nombre and not correo:
            continue  # fila vacía

        # H: mensualidad (solo depende de la hoja).
        costo_num = parse_number(costo)
        meses_num = parse_number(meses)
        mensualidad = None
        if costo_num is not None and meses_num not in (None, 0):
            mensualidad = round(costo_num / meses_num, 2)

        # D y E: dependen del emparejamiento con el formulario.
        especialidad = ""
        curso = ""
        match, score = best_match(nombre, correo, records)
        if match:
            n_matched += 1
            especialidad = match["carrera"].strip()
            curso = first_word(match["curso_values"][0]) if match["curso_values"] else ""
            flag = "  ⚠ nombre poco similar" if score < NAME_WARN_THRESHOLD else ""
            print(
                f"  Fila {sheet_row}: «{nombre}» -> «{match['name_student'] or match['name_tutor']}»"
                f" (sim {score:.0f}) | {especialidad} | {curso}{flag}"
            )
        else:
            n_not_found += 1
            print(f"  Fila {sheet_row}: «{nombre}» / «{correo}» -> SIN RESPUESTA en el form")

        # Programar escrituras (respetando fill-if-empty / overwrite).
        def schedule(col_letter: str, col_index: int, value) -> None:
            if value in (None, ""):
                return
            current = cell(row, col_index)
            if current and not OVERWRITE:
                return
            updates.append(
                {"range": f"'{SHEET_NAME}'!{col_letter}{sheet_row}", "values": [[value]]}
            )

        schedule("D", 3, especialidad)
        schedule("E", 4, curso)
        schedule("H", 7, mensualidad)

    print(
        f"\nResumen: {n_matched} emparejadas, {n_not_found} sin respuesta, "
        f"{len(updates)} celdas por escribir."
    )

    if not updates:
        print("Nada que escribir.")
        return

    if DRY_RUN:
        print("DRY_RUN activo: no se escribe nada.")
        for u in updates:
            print(f"  {u['range']} = {u['values'][0][0]}")
        return

    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates},
    ).execute()
    print("Hoja actualizada correctamente.")


if __name__ == "__main__":
    main()
