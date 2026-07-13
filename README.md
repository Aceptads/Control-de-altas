# Control de altas — Aceptados

Automatiza el llenado de la hoja **Altas** cruzando cada alumno con las
respuestas del Google Form de inscripción.

## Qué hace

Para cada fila de la hoja `Altas` se leen los datos que tú capturas:

| Columna | Dato (lo capturas tú) |
|---------|------------------------|
| A | Nombre |
| C | Correo de contacto |
| F | Costo |
| G | Meses a pagar |

El script busca la respuesta del formulario cuyo **correo** (pregunta
*"CORREO DEL ALUMNO"*) coincida **exactamente** con la columna C, y usa el
**nombre** como confirmación (tolera acentos y el orden apellido/nombre;
compara contra *"NOMBRE COMPLETO DEL ALUMNO"* y *"NOMBRE DEL PADRE O TUTOR"*).
Con esa respuesta llena:

| Columna | Se completa con |
|---------|------------------|
| D | Especialidad → *"CARRERA O LICENCIATURA A LA QUE DESEA INGRESAR"* |
| E | Curso → **primera palabra** de *"CURSO QUE DESEA TOMAR"* (p. ej. `UNAM`, `IPN`, `UAEH`) |
| H | Mensualidad → Costo (F) ÷ Meses (G) |

Por defecto **solo rellena celdas vacías** (no pisa correcciones manuales).

## Envío automático de documentación (columnas I y J)

Además de llenar la hoja, el script envía por correo la **documentación de
inscripción** al alumno (columna **C**), desde `aceptados.cursos@gmail.com`,
con tres adjuntos que viven en la carpeta `docs/` del repo:

- FO-04 Carta Compromiso Rev.02
- FO-02 Reglamento Rev.02
- FO-03 Políticas Rev.02

El asunto y el cuerpo salen de la carpeta `plantilla/` (`asunto.txt` y
`cuerpo.html`, editables sin tocar código; admiten el marcador `{nombre}`).

Dos columnas controlan el envío:

| Columna | Significado |
|---------|-------------|
| **I** | *Documentación enviada* → se pone en `Si` cuando se envía |
| **J** | *Alta* → también `Si` al enviar; es el **interruptor manual** |

Lógica:

- **I en blanco** → nunca se ha enviado: se envía y se marca I = `Si`, J = `Si`.
- **I = `Si`** → ya fue alta: la fila **se ignora**.
- **J = `No`** (lo pones tú a mano cuando corriges un dato: correo, nombre,
  costo…) → la fila **se vuelve a considerar** y se reenvía la documentación;
  al reenviar, J vuelve a `Si`.

En **Dry-run** no envía ni escribe: solo muestra a quién enviaría.

## Clave / folio (columna K)

La columna **K "Clave"** se llena con la clave del curso + un folio consecutivo,
tomando el catálogo de la pestaña **Claves** (`Curso`, `Especialidad`, `Clave`):

- **Escuela sin especialidad** (`SN` o vacía en Claves) → se usa solo la escuela:
  `UNAM-001`, `UNAM-002`, `IPN-001`…
- **Escuela con especialidad** → se empareja la **carrera (columna D)** contra la
  columna *Especialidad* de Claves y se usa la clave completa: `UAM-CBI-001`,
  `UAEH-MEDICINA-001`…

El **folio se cuenta por cada clave** (cada una arranca en `001`) y continúa a
partir del folio más alto que ya exista en la columna K, para **no reasignar**
folios (una clave asignada es permanente; solo se llena si K está vacía).

Si el curso no está en Claves, o es una escuela con especialidades y no se puede
determinar cuál, la fila se deja **sin clave** (y se avisa en el log).

## Cómo ejecutarlo (botón manual)

1. Ve a la pestaña **Actions** del repositorio.
2. Elige **Control de altas** en la lista de la izquierda.
3. Clic en **Run workflow**. Opcionalmente marca:
   - *Solo mostrar* → simula sin escribir nada (útil para probar).
   - *Sobrescribir* → pisa también celdas que ya tengan contenido.

## Configuración inicial (una sola vez)

Ya tienes el JSON de la cuenta de servicio. Falta conectarla:

1. **Habilitar APIs** en el proyecto de Google Cloud de esa cuenta:
   - *Google Sheets API*
   - *Google Forms API*

2. **Compartir la hoja de cálculo** con el correo de la cuenta de servicio
   (el campo `client_email` del JSON, algo como `...@...iam.gserviceaccount.com`)
   con permiso de **Editor**.

3. **Compartir el formulario** con ese mismo correo como **colaborador**
   (en el Form: menú ⋮ → *Agregar colaboradores*).

4. **Guardar el JSON como secreto en GitHub**:
   - Repo → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*.
   - Nombre: `GOOGLE_SERVICE_ACCOUNT_JSON`
   - Valor: pega el contenido completo del archivo JSON.

## Configuración del envío de correo (una sola vez)

El envío usa **OAuth** de la cuenta `aceptados.cursos@gmail.com` (una cuenta de
servicio no puede enviar como una dirección `@gmail.com`). Se genera un
*refresh token* una vez y se guarda como secreto.

1. En Google Cloud Console: habilita la **Gmail API**; en la pantalla de
   consentimiento OAuth agrega el scope `.../auth/gmail.send`, añade
   `aceptados.cursos@gmail.com` como usuario de prueba y pon el estado
   **"En producción"** (para que el token no caduque a los 7 días).
2. Crea credenciales → **ID de cliente de OAuth** → **App de escritorio** y
   descarga el JSON como `client_secret.json`.
3. En tu computadora (con Python): `pip install google-auth-oauthlib` y luego
   `python get_gmail_token.py`. Inicia sesión con `aceptados.cursos@gmail.com`.
4. Guarda como secretos del repo los tres valores que imprime:
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`.

## Variables de entorno (opcionales)

Se pueden ajustar en el `env` del workflow:

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `SPREADSHEET_ID` | *(la hoja de Altas)* | ID de la hoja de cálculo |
| `FORM_ID` | *(el form de inscripción)* | ID del formulario |
| `SHEET_NAME` | `Altas` | Nombre de la pestaña |
| `HEADER_ROWS` | `1` | Filas de encabezado antes de los datos |
| `OVERWRITE` | `false` | Sobrescribir celdas con contenido |
| `DRY_RUN` | `false` | Simular sin escribir ni enviar |
| `SEND_DOCS` | `true` | Enviar la documentación por correo |

## Seguridad

El archivo JSON de credenciales **nunca** se sube al repo (ver `.gitignore`).
Vive únicamente como secreto de GitHub Actions.
