# deep

```
  深度求索
  deep · agente DeepSeek
```

**deep** es un agente de programación para la terminal, al estilo de Claude Code, con
**DeepSeek** por debajo. Le hablás en lenguaje natural y el agente resuelve la tarea
operando sobre tu proyecto con herramientas: lee, busca, escribe código, corre comandos
y verifica su propio trabajo, iterando hasta terminar.

No es un generador de "un disparo": es un **loop conversacional con tools**. Un modelo
fuerte (PRO) entiende la tarea, escribe el código y lo verifica; un modelo rápido (FLASH)
hace el trabajo barato de lectura/resumen. Todo corre local — tu código y tu API key se
quedan en tu máquina.

> **Filosofía de calidad:** el modelo fuerte escribe el código que importa. No delegamos la
> calidad para ahorrar tokens (DeepSeek ya es barato). Ver [PHILOSOPHY.md](PHILOSOPHY.md).

---

## Instalación

### PyPI

```bash
pip install deepseek-builder
```

### Linux / macOS

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/cynchro/deepseekCLI/main/install.sh)
```

O desde el repositorio clonado:

```bash
git clone https://github.com/cynchro/deepseekCLI.git
cd deepseekCLI
bash install.sh
```

### Windows

Desde PowerShell (requiere Python 3.9+ instalado):

```powershell
git clone https://github.com/cynchro/deepseekCLI.git
cd deepseekCLI
.\install.ps1
```

O de forma remota:

```powershell
irm https://raw.githubusercontent.com/cynchro/deepseekCLI/main/install.ps1 | iex
```

> El instalador crea un entorno virtual en `~\.local\share\deepseekcli`, agrega el comando `deep` al PATH de usuario, y guarda la API key como variable de entorno de Windows. Abrí una nueva terminal después de instalar.

### Configuración de la API key

La primera vez que ejecutes `deep` te pedirá la API key y la guardará automáticamente. Obtené la tuya en [platform.deepseek.com](https://platform.deepseek.com/api_keys).

Para cambiarla más adelante:

```bash
deep config set-key
```

O con una variable de entorno (tiene prioridad sobre el archivo de config):

```bash
# Linux/macOS
export DEEPSEEK_API_KEY=tu_key_aqui

# Windows PowerShell
$env:DEEPSEEK_API_KEY = "tu_key_aqui"

# Windows (permanente)
setx DEEPSEEK_API_KEY "tu_key_aqui"
```

---

## Uso

### REPL del agente (por defecto)

```bash
deep
```

Abre el REPL agente-first con autocompletado e historial. Escribís lo que querés hacer en
**lenguaje natural** y el agente lo resuelve; los `/comandos` (slash) controlan la sesión.

```
deep ❯ agregá un endpoint /health a la API que devuelva {"status":"ok"} y un test
deep ❯ /mode auto
deep ❯ refactorizá el módulo de auth para que use el nuevo cliente http
deep ❯ /cost
```

### Modo directo (scripting / una sola tarea)

```bash
deep agent "escribí un script que renombre los .jpeg a .jpg en este dir"
deep agent "corré los tests y arreglá lo que falle" -y     # -y = sin pedir permisos
deep agent "..." -w ./mi-proyecto                          # workspace específico
```

`deep agent` lanza el mismo loop pero para una sola tarea y termina.

---

## Cómo trabaja el agente

El núcleo es un **loop con tool calling** (`core/agent_loop.py`). En cada paso el modelo
decide qué herramienta llamar, observa el resultado e itera hasta resolver la tarea:

1. **Explora** el proyecto (`list_dir`, `glob`, `grep`, `read_file`) para entender la estructura y las convenciones.
2. **Escribe** el código (`write_file`, `edit_file`) — el modelo fuerte lo escribe directo, no lo delega.
3. **Verifica** corriendo tests/lint/el programa (`run_command`) e itera sobre los fallos.
4. **Cierra** con un resumen de lo que hizo y cómo lo probó.

### Herramientas del agente

| Tool | Qué hace |
|------|----------|
| `read_file` / `list_dir` / `glob` / `grep` | Exploración y lectura (determinista, sin LLM). |
| `search_code` | Recuperación por **relevancia** (índice BM25 local, incremental): ubica "dónde se hace X" en codebases grandes y devuelve los fragmentos más pertinentes con `archivo:línea`. Mejor que grep para orientarse. |
| `write_file` / `edit_file` | Crear / editar archivos. **El modelo fuerte escribe acá.** `edit_file` es un reemplazo de string quirúrgico (no reescribe el archivo entero). |
| `run_command` | Corre comandos de shell en el workspace (tests, git, instalar deps), con permiso. |
| `explore` | Investigación **read-only delegada a FLASH**: le hacés una pregunta sobre el código y un agente lector devuelve un resumen compacto, sin gastar el contexto caro del orquestador. |
| `generate_code` / `apply_edit` | Generación/edición **delegada a FLASH** — excepción, para volumen mecánico de bajo riesgo (boilerplate, scaffolding). `apply_edit` usa bloques SEARCH/REPLACE quirúrgicos. |
| `write_tasks` / `update_task` | Lista de tareas persistente (`.deep/tasks.json`) para trabajos largos. |
| `spawn_agent` | Delega una parte grande y autocontenida a un sub-agente con contexto fresco. |

### Lo que lo acerca a Claude Code

- **El modelo fuerte escribe el código**, no un modelo más débil. La calidad no se sacrifica para ahorrar tokens.
- **Edición quirúrgica**: `edit_file` cambia solo las líneas que tocan; nunca reescribe archivos enteros para un cambio puntual.
- **Diffs visibles**: cada edición muestra el diff real (coloreado) y se lo devuelve al modelo para que **auto-revise** lo que escribió.
- **Verificación automática**: al cerrar un turno que tocó código, `deep` corre los tests del proyecto (pytest / `npm test` detectados) y, si están en rojo, reinyecta el fallo al loop hasta dejarlo en verde. Respeta los permisos (en modo `plan` o remoto no corre).
- **Guard read-before-edit**: editar un archivo que no se leyó en la sesión se bloquea, para no inventar su contenido.
- **Contexto liviano**: `explore` y la compactación automática usan FLASH para que el orquestador no se llene la cabeza con archivos enteros.

---

## Slash commands (en el REPL)

| Comando | Qué hace |
|---------|----------|
| `/init` | Explora el proyecto y escribe/actualiza `DEEP.md` (el contexto del proyecto). |
| `/mode [ask\|auto\|plan\|yolo]` | Cambia el modo de permisos (ver abajo). Sin argumento muestra el actual. |
| `/model [pro\|flash]` | Modelo orquestador del loop (default: `pro`). |
| `/tasks` | Muestra el plan de tareas persistente. |
| `/rules` | Muestra el `DEEP.md` y `.deeprules` cargados. |
| `/skills` · `/skill <n> <tarea>` | Lista skills / corre una tarea aplicando un skill. |
| `/cost` | Tokens y costo estimado por modelo de la sesión (con cache hits). |
| `/clear` · `/new` | Reinicia la conversación del agente. |
| `/balance` `/history` `/doctor` `/show` `/serve` `/upgrade` | Comandos legacy (passthrough). |
| `/help` · `/exit` `/quit` | Ayuda / salir. |

### Permisos / modos

`deep` pide permiso antes de tocar disco o ejecutar shell. Cuatro modos:

| Modo | Comportamiento |
|------|----------------|
| `ask` (default) | Pregunta antes de escribir y de ejecutar. Respondé `a` para no volver a preguntar en la sesión. |
| `auto` | Acepta ediciones de archivos automáticamente; el shell sigue preguntando. |
| `plan` | Solo lectura: bloquea escrituras y shell (incluida la verificación automática). |
| `yolo` | Acepta todo sin preguntar. |

---

## Modelos

`deep` usa dos modelos de DeepSeek con un split por rol:

| Rol | Modelo | Para qué |
|-----|--------|----------|
| Orquestar, **escribir código**, revisar, verificar | **`deepseek-v4-pro`** | El cerebro y las manos. Decide y escribe lo que importa. |
| Leer/resumir (`explore`, compactación) y volumen mecánico (`generate_code`/`apply_edit`) | **`deepseek-v4-flash`** | ~3× más barato. Trabajo de bajo riesgo y alto volumen. |

Cambiás el orquestador con `/model pro|flash`. La telemetría (`/cost`) desglosa tokens y
costo por modelo, contemplando el **prompt caching** (los prefijos cacheados se cobran ~100× menos).

> **Migración:** los IDs viejos `deepseek-chat` y `deepseek-reasoner` están **deprecados
> (sunset 2026-07-24)**. `deep` los acepta por compatibilidad y los mapea a los modelos v4
> (`chat`→`flash`, `reasoner`→`pro`), pero usá los IDs v4 directamente.

---

## Contexto del proyecto: `DEEP.md` y `.deeprules`

- **`DEEP.md`** es el "CLAUDE.md de deep": instrucciones autoritativas del proyecto que se
  inyectan al agente. Es jerárquico — se cargan el global (`~/.config/deep/DEEP.md`) y el del
  proyecto (`./DEEP.md`). Generalo con `/init`: el agente explora el repo y lo escribe
  (stack, estructura, cómo correr/testear, convenciones).
- **`.deeprules`** es una lista simple de reglas (una por línea) que también se inyecta. Sigue
  funcionando por compatibilidad.

```
# .deeprules
Usá type hints en todo el código Python.
Los tests van en tests/ con pytest.
No agregues dependencias sin avisar.
```

---

## Skills

Un **skill** es una capacidad nombrada (descripción + instrucciones) que el agente aplica a
una tarea. Se cargan desde `~/.config/deep/skills/*.skill` (globales) y `./.skill`/`.deep/skills`
del proyecto.

```bash
deep ❯ /skills                          # lista los disponibles
deep ❯ /skill reviewer revisá el módulo de pagos
```

Hay ejemplos en [`examples/skills/`](examples/skills/) (reviewer, security, docs, refactor, explainer).

---

## Trabajos grandes: tareas persistentes y subagentes

- **Lista de tareas persistente** (`.deep/tasks.json`): para trabajos de varios pasos, el agente
  descompone el trabajo con `write_tasks` y marca el progreso con `update_task`. Se inyecta al
  arrancar, así un build grande **sobrevive** al límite de pasos, al `continuá` y al reinicio.
  Vela con `/tasks`.
- **Subagentes** (`spawn_agent`): el agente delega una parte grande y autocontenida (un módulo,
  un subsistema) a un sub-agente con contexto fresco, que devuelve un resumen compacto — el
  orquestador se mantiene liviano. Con guardas de profundidad y aislamiento del plan global.
  Si emite **varios `spawn_agent` en el mismo turno** (partes independientes entre sí), corren
  **en paralelo** (threads); el padre verifica una sola vez al final con lo que tocaron todos.
- **Compactación automática**: cuando el historial crece, los turnos viejos se resumen con FLASH
  preservando objetivo, archivos tocados, decisiones y pendientes.

---

## `serve` — usar deep desde el celular (PWA)

```bash
deep serve              # HTTP básico
deep serve --https      # HTTPS + instalable como app
deep serve --tunnel     # túnel HTTPS público (cómodo para instalar como PWA)
deep serve --port 9000 --https
```

Levanta una interfaz web (FastAPI) accesible desde cualquier dispositivo en la red. Incluye un
toggle **🤖 Agente** que rutea el texto natural al agent loop por streaming (SSE), mostrando la
actividad de tools en vivo y el costo por modelo. Por seguridad, en remoto las **escrituras** se
permiten pero el **shell está bloqueado** salvo que pongas `DEEP_REMOTE_SHELL=1`.

#### Recomendación: Tailscale

[Tailscale](https://tailscale.com) es la forma más cómoda y segura de acceder a `deep serve`
desde el celular aunque estén en redes distintas: te da una IP fija `100.x.x.x` que no cambia y
no requiere abrir puertos. Instalalo en la compu y en el celular con la misma cuenta; con
Tailscale activo, `deep serve --https` muestra directamente la URL `100.x.x.x`.

#### Instalar como app (PWA)

Para instalar `deep` como app nativa en el celular la conexión tiene que ser HTTPS.
`deep serve --https` genera el certificado automáticamente (requiere `trustme`:
`pip install "deepseek-builder[https]"`).

1. Abrí en el celular la **URL del Paso 1** que muestra `deep serve --https` e instalá el certificado CA:
   - **Android:** Ajustes → Seguridad → Cifrado y credenciales → Instalar un certificado → Certificado de CA
   - **iOS:** al abrir el `.pem` → "Perfil descargado" → Ajustes → General → VPN y administración → Instalar → Confiar
2. Abrí la **URL del Paso 2** (`https://100.x.x.x:8000`) — aparece el botón **⬇** en la cabecera.
3. Tap en **⬇** → la app se instala como nativa. No hace falta repetir el proceso.

> El certificado autofirmado es local y temporal, solo para que el navegador acepte HTTPS en tu red privada. No sale a internet.

---

## Comandos legacy (single-shot)

`deep` nació como generador de "un disparo" y esos comandos siguen funcionando para scripting y
para la PWA. El agente (arriba) los reemplaza en el uso diario, pero no se retiran:

| Comando | Qué hace |
|---------|----------|
| `deep build "tarea" [-f]` | Genera un proyecto completo en una llamada (`-f` corrige si la evaluación falla). |
| `deep update "cambio"` | Modifica el proyecto del directorio actual. |
| `deep ask "pregunta"` | Pregunta al modelo sin generar proyecto. |
| `deep claudejob [--init\|--review\|--fix]` | Flujo donde un LLM externo (Claude) planifica en `job.md` y DeepSeek construye/corrige módulo por módulo. |
| `deep show` | Muestra el contexto del proyecto actual. |

> El REPL clásico (no-agente) sigue disponible con `DEEP_CLASSIC_REPL=1 deep`.

---

## Diagnóstico y mantenimiento

```bash
deep doctor      # verifica Python, API key, conexión, deps y PATH (Linux/macOS/Windows)
deep upgrade     # actualiza el CLI desde GitHub
deep balance     # crédito de la cuenta DeepSeek
deep history     # experiencias acumuladas
deep config      # muestra la configuración (config set-key / set-lang para cambiarla)
```

---

## Debug

Cualquier comando acepta `--debug`, que escribe un `debug.log` paso a paso en el directorio actual:

```bash
deep --debug agent "tarea"
```

El log registra cada llamada a la API (modelo, tokens, latencia, finish_reason), cada tool call
con sus argumentos y resultado, y los eventos del loop (compactación, verificación, subagentes).
Útil para entender qué hizo el agente y dónde se fue el costo.

```bash
grep API_CALL debug.log | wc -l          # cuántas llamadas a la API
grep "tool=" debug.log                    # qué tools llamó
grep -E "API_ERR|max_steps" debug.log     # errores o reintentos
tail -f debug.log                          # seguir en tiempo real
```

---

## Requisitos

- Python 3.9+
- Una API key de DeepSeek
- Conexión a internet

### Dependencias opcionales

```bash
pip install prompt_toolkit          # autocompletado e historial en el REPL
pip install "deepseek-builder[https]"   # trustme, para deep serve --https
```

Sin `prompt_toolkit` el REPL funciona igual pero en modo básico. Sin `trustme`, `deep serve --https` muestra un error con las instrucciones de instalación.

---

## Compatibilidad

Funciona en Linux, macOS y Windows 10+ (con secuencias ANSI habilitadas automáticamente).

---

## Changelog

Ver [CHANGELOG.md](CHANGELOG.md). Versión actual: **0.4.0**.

## Philosophy

Ver [PHILOSOPHY.md](PHILOSOPHY.md).

## Contributing

Ver [CONTRIBUTING.md](CONTRIBUTING.md).

## Code of Conduct

Ver [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Contact

**alexissaucedo@gmail.com** · [cynchrolabs.com.ar](https://www.cynchrolabs.com.ar)

## Buy me a coffee?

Si `deep` te ahorró tiempo, considerá una donación — ayuda a mantener el proyecto.

<a href="https://www.paypal.com/donate/?hosted_button_id=YX332RT7KSJ4Q">
  <img src="https://img.shields.io/badge/PayPal-Donate-blue?logo=paypal" alt="Donate with PayPal"/>
</a>

---

⭐ Si te gusta el proyecto, ¡dale una estrella!

<a href="https://github.com/cynchro/deepseekCLI">
  <img src="https://img.shields.io/github/stars/cynchro/deepseekCLI?style=social" alt="GitHub stars"/>
</a>
