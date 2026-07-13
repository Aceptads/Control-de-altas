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

from send_docs import build_gmail_service, send_docs

# --------------------------------------------------------------------------- #
# Configuración (los valores por defecto se pueden sobreescribir por entorno)  #
# --------------------------------------------------------------------------- #
SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "10mn2MK2ipBTpbcVm2wl4lUVfHt-WXuTFRoM88dxEUuc"
)
FORM_ID = os.environ.get("FORM_ID", "1m5UruvwSlDdvGrMqKnrMQs3ptN1lLgD51sIGA7wHfUA")
SHEET_NAME = os.environ.get("SHEET_NAME", "Altas")
# Pestaña con el catálogo de claves (Curso, Especialidad, Clave).
CLAVES_SHEET = os.environ.get("CLAVES_SHEET", "Claves")

# Número de filas de encabezado antes de que empiecen los datos.
HEADER_ROWS = int(os.environ.get("HEADER_ROWS", "1"))

# Si es "true", sobrescribe celdas que ya tengan contenido. Por defecto solo
# rellena celdas vacías (no pisa correcciones manuales).
OVERWRITE = os.environ.get("OVERWRITE", "false").lower() == "true"

# Si es "true", muestra lo que haría pero no escribe en la hoja.
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# Si es "true", envía la documentación de inscripción por Gmail a los alumnos
# cuya fila lo requiera (ver lógica de columnas I/J más abajo).
SEND_DOCS = os.environ.get("SEND_DOCS", "true").lower() == "true"

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


def norm_si(text: str) -> str:
    """Normaliza un 'Sí'/'si'/'SI' -> 'si' y un 'No'/'NO' -> 'no' (sin acentos)."""
    return strip_accents((text or "").strip().lower())


def valid_email(text: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (text or "").strip()))


def first_word(text: str) -> str:
    text = (text or "").strip()
    return text.split()[0] if text else ""


def parse_number(value) -> float | None:
    """Convierte 3000, '3000', '$3,000.00' -> float. Devuelve None si no se puede.

    La hoja se lee con UNFORMATTED_VALUE, así que los números llegan ya como
    int/float (sin ambigüedad de separador de miles). El parseo de texto es
    solo un respaldo para cuando alguien captura el costo como texto.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^0-9.,-]", "", str(value).strip())
    s = s.replace(",", "")  # respaldo: ',' como separador de miles
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
# Claves / folios                                                              #
# --------------------------------------------------------------------------- #
def load_claves(sheets) -> dict:
    """Lee la pestaña Claves (Curso, Especialidad, Clave) -> {curso_norm: [..]}."""
    result = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{CLAVES_SHEET}'!A2:C",
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    by_curso: dict[str, list[dict]] = {}
    for r in result.get("values", []):
        curso = cell(r, 0)
        if not curso:
            continue
        esp = cell(r, 1)
        clave = cell(r, 2)
        by_curso.setdefault(norm_title(curso), []).append(
            {"curso": curso, "esp_norm": norm_title(esp), "clave": clave}
        )
    return by_curso


# La carrera capturada (col D) NO siempre trae la sigla: puede venir el nombre
# completo o un pedazo. Aquí se mapea cada clave a sus nombres completos para
# poder emparejarla. Ampliable: agrega más entradas conforme aparezcan casos.
ESPECIALIDAD_ALIASES = {
    "UAM-CBI": ["Ciencias Básicas e Ingenierías"],
    "UAM-CBS": ["Ciencias Biológicas y de la Salud"],
    "UAM-CSH": ["Ciencias Sociales y Humanidades"],
    "UAM-CYAD": ["Ciencias y Artes para el Diseño"],
}

# Umbral (0-100) de similitud difusa para emparejar la carrera con el NOMBRE
# COMPLETO de una especialidad cuando no hay coincidencia exacta ni por sigla.
ESP_FUZZ_THRESHOLD = int(os.environ.get("ESP_FUZZ_THRESHOLD", "82"))


def _esp_match_score(carrera_norm: str, target_norm: str) -> float:
    """Qué tanto se parece la carrera a un objetivo (sigla o nombre completo)."""
    if not target_norm:
        return 0.0
    if carrera_norm == target_norm:
        return 100.0
    if len(target_norm) <= 5:
        # Es una sigla (CBI, CSH…): exige que aparezca como palabra completa;
        # NO se usa difuso porque con siglas es poco fiable.
        if re.search(rf"(^|\W){re.escape(target_norm)}(\W|$)", carrera_norm):
            return 95.0
        return 0.0
    # Nombre completo: contención o similitud difusa (tolera pedazos/typos).
    if target_norm in carrera_norm or carrera_norm in target_norm:
        return 90.0
    return float(fuzz.token_set_ratio(carrera_norm, target_norm))


def _cand_score(carrera_norm: str, cand: dict) -> float:
    targets = [cand["esp_norm"]]
    targets += [norm_title(a) for a in ESPECIALIDAD_ALIASES.get(norm_title(cand["clave"]), [])]
    return max((_esp_match_score(carrera_norm, t) for t in targets), default=0.0)


def clave_base(curso: str, carrera: str, by_curso: dict) -> tuple[str | None, str]:
    """Devuelve (base, error). La base es la clave SIN el folio.

    - Escuela sin especialidad (esp 'SN' o vacía): base = la escuela (p.ej. UNAM).
    - Escuela con especialidades: se empareja la carrera (col D) contra la sigla
      Y el nombre completo de cada especialidad (tolerante a nombre completo,
      pedazos y acentos); base = la clave completa (p.ej. UAM-CBI).
    """
    cands = by_curso.get(norm_title(curso))
    if not cands:
        return None, "curso no está en la hoja Claves"

    sn = [c for c in cands if c["esp_norm"] in ("SN", "")]
    if sn:
        return sn[0]["curso"], ""

    d = norm_title(carrera)
    if not d:
        return None, "no pude determinar la especialidad (col D vacía)"

    scored = sorted(((_cand_score(d, c), c) for c in cands), key=lambda x: x[0], reverse=True)
    top = scored[0][0]
    if top < ESP_FUZZ_THRESHOLD:
        return None, f"la carrera «{carrera}» no coincide con ninguna especialidad"
    winners = {c["clave"] for s, c in scored if s == top}
    if len(winners) > 1:
        return None, f"la carrera «{carrera}» es ambigua entre {sorted(winners)}"
    return scored[0][1]["clave"], ""


# --------------------------------------------------------------------------- #
# Proceso principal                                                            #
# --------------------------------------------------------------------------- #
def cell(row: list, index: int) -> str:
    """Devuelve el valor de la celda como texto (los números llegan como int/float
    por leer con UNFORMATTED_VALUE, así que se convierten a str de forma segura)."""
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def main() -> None:
    print("== Control de altas ==")
    print(f"  Hoja: {SHEET_NAME}  |  Overwrite: {OVERWRITE}  |  Dry-run: {DRY_RUN}")

    sheets, forms = build_services()

    gmail = None
    if SEND_DOCS:
        gmail = build_gmail_service()
        if gmail is None:
            print(
                "  [aviso] Faltan credenciales de Gmail "
                "(GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN); "
                "no se enviará documentación."
            )

    print("Leyendo respuestas del formulario...")
    records = load_form_records(forms)
    print(f"  {len(records)} respuestas cargadas.")

    print("Leyendo catálogo de claves...")
    by_curso = load_claves(sheets)
    print(f"  {sum(len(v) for v in by_curso.values())} claves cargadas.")

    print("Leyendo hoja Altas...")
    read_range = f"'{SHEET_NAME}'!A1:K"
    result = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=SPREADSHEET_ID,
            range=read_range,
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    rows = result.get("values", [])
    data_rows = rows[HEADER_ROWS:]
    print(f"  {len(data_rows)} filas de datos.")

    updates: list[dict] = []
    n_matched = 0
    n_not_found = 0
    n_docs = 0
    n_claves = 0

    # Folios por clave: arranca en el máximo ya presente en la columna K para
    # NO reasignar folios existentes (una clave asignada es permanente).
    folio_counters: dict[str, int] = {}
    folio_re = re.compile(r"^(.*)-(\d+)$")
    for row in data_rows:
        existing = cell(row, 10)  # K
        m = folio_re.match(existing) if existing else None
        if m:
            base, num = m.group(1), int(m.group(2))
            folio_counters[base] = max(folio_counters.get(base, 0), num)

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

        # I y J: envío de documentación de inscripción.
        #   I "Documentación enviada": se pone "Si" al enviar.
        #   J "Alta": también "Si" al enviar; es el interruptor manual: si
        #   alguien lo pone en "No" (porque cambió un dato) se vuelve a enviar.
        # Se envía si I está en blanco (nunca enviada) o si J dice "No".
        enviada = norm_si(cell(row, 8))  # I
        alta = norm_si(cell(row, 9))     # J
        should_send = (enviada != "si") or (alta == "no")

        if SEND_DOCS and gmail and should_send:
            if not valid_email(correo):
                print(f"    → sin correo válido en C; no se envía documentación")
            elif DRY_RUN:
                print(f"    → (dry-run) enviaría documentación a {correo}")
                n_docs += 1
            else:
                try:
                    send_docs(gmail, correo, nombre)
                    n_docs += 1
                    print(f"    → documentación enviada a {correo}")
                    # Estado: se escribe siempre (no depende de OVERWRITE).
                    updates.append(
                        {"range": f"'{SHEET_NAME}'!I{sheet_row}", "values": [["Si"]]}
                    )
                    updates.append(
                        {"range": f"'{SHEET_NAME}'!J{sheet_row}", "values": [["Si"]]}
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"    → ERROR al enviar a {correo}: {exc}")

        # K: clave + folio. Solo se asigna si la celda está vacía (un folio no
        # se reasigna). Usa la escuela (E) y la carrera (D); si esas celdas aún
        # están vacías, cae a los valores recién calculados del formulario.
        if not cell(row, 10):
            curso_e = cell(row, 4) or curso
            carrera_d = cell(row, 3) or especialidad
            base, err = clave_base(curso_e, carrera_d, by_curso)
            if base:
                folio_counters[base] = folio_counters.get(base, 0) + 1
                clave_val = f"{base}-{folio_counters[base]:03d}"
                updates.append(
                    {"range": f"'{SHEET_NAME}'!K{sheet_row}", "values": [[clave_val]]}
                )
                n_claves += 1
                print(f"    → clave {clave_val}")
            elif curso_e:
                print(f"    → sin clave: {err}")

    print(
        f"\nResumen: {n_matched} emparejadas, {n_not_found} sin respuesta, "
        f"{n_docs} con documentación enviada, {n_claves} claves asignadas, "
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
