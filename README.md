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

> Las columnas **I** y **J** quedan pendientes de definir.

Por defecto **solo rellena celdas vacías** (no pisa correcciones manuales).

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

## Variables de entorno (opcionales)

Se pueden ajustar en el `env` del workflow:

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `SPREADSHEET_ID` | *(la hoja de Altas)* | ID de la hoja de cálculo |
| `FORM_ID` | *(el form de inscripción)* | ID del formulario |
| `SHEET_NAME` | `Altas` | Nombre de la pestaña |
| `HEADER_ROWS` | `1` | Filas de encabezado antes de los datos |
| `OVERWRITE` | `false` | Sobrescribir celdas con contenido |
| `DRY_RUN` | `false` | Simular sin escribir |

## Seguridad

El archivo JSON de credenciales **nunca** se sube al repo (ver `.gitignore`).
Vive únicamente como secreto de GitHub Actions.
