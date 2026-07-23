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
> calidad para ahorrar tokens (DeepSeek ya es barato). Ver [PHILOSOPHY.md](doc/PHILOSOPHY.md).

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

### Desinstalación

Si instalaste con `install.sh`/`install.ps1` (el venv aislado, no la vía PyPI):

```bash
# Linux/macOS — desde el repo clonado
bash uninstall.sh          # borra el programa; deja tu API key/idioma/historial
bash uninstall.sh --purge  # además borra ~/.config/deep
```

```powershell
# Windows
.\uninstall.ps1            # borra el programa y lo saca del PATH de usuario
.\uninstall.ps1 -Purge     # además borra la config
```

Borran el entorno virtual (`~/.local/share/deepseekcli`) y el comando `deep`. En
Windows también sacan esa ruta del PATH de usuario (el instalador la agrega ahí
directo); en Linux/macOS, si vos mismo agregaste `~/.local/bin` a tu `PATH` a mano,
no lo tocamos automáticamente —ese directorio lo comparten otras herramientas (por
ejemplo `pip install --user`), así que sacarlo a ciegas podría romper algo más.

Si instalaste con `pip install deepseek-builder` (PyPI): `pip uninstall deepseek-builder`.

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

### Workspace remoto (SSH)

`deep` puede operar sobre una carpeta en **otra máquina** vía SSH —leer, editar, listar
y ejecutar comandos ahí— sin instalar nada en la remota (solo hace falta `sshd` corriendo):

```bash
pip install "deepseek-builder[ssh]"   # paramiko

# una sola tarea y termina (igual que `deep agent` local)
deep agent "corré los tests y arreglá lo que falle" --host usuario@servidor -w /home/usuario/mi-proyecto

# REPL interactivo: te quedás trabajando ahí, turno tras turno, sin reconectar cada vez
deep remote --host usuario@servidor -w /home/usuario/mi-proyecto

# en cualquiera de los dos, sin -w se abre un picker para navegar hasta la carpeta
deep remote --host usuario@servidor
```

¿No te acordás la sintaxis completa? Corré `deep` normal (local) y escribí **`/remote`** — te
pregunta el host paso a paso y abre el mismo picker, sin salir del REPL ni tener que
recordar flags. Para volver a trabajar en local sin salir de `deep`, usá **`/disconnect`**
(o su alias `/logout`).

- **Auth**: solo clave SSH / ssh-agent, reusando tu `~/.ssh/config` y `known_hosts` tal
  cual los tenés configurados (igual que un `ssh` normal). No pide ni guarda passwords.
  Si el host no está en `known_hosts` todavía, conectate una vez a mano con `ssh` antes.
- **Sin `-w`**: se abre un picker de carpetas arrancando en el home remoto — un número
  entra a esa subcarpeta, `..` sube un nivel, una ruta absoluta salta directo ahí, y
  Enter confirma la carpeta actual como workspace. Ctrl-C/Ctrl-D cancela.
- **`deep remote`** te deja en el mismo REPL que `deep` local (los `/comandos`, el chat,
  todo), salvo `/scan` y `/show` (dependen del scanner legacy, no soportado todavía
  contra un workspace remoto).
- Todas las tools (`read_file`, `write_file`, `grep`, `search_code`, `run_command`, etc.)
  funcionan igual que en local; `run_command` corre en la remota.
- **Windows también anda** (verificado en vivo contra un Win32-OpenSSH real): detecta
  el SO automáticamente al conectar, `run_command` arma sintaxis `cmd.exe` (el agente
  usa `dir`/`type`/`findstr`, no `ls`/`grep`/`cat`), y `-w`/el picker aceptan rutas
  nativas (`C:\Users\alexis\proyecto`). PowerShell como shell default no está
  soportado todavía (falla con un mensaje claro, en vez de comandos rotos).
  Dos límites conocidos: (1) `type`/`findstr` sobre un archivo con tildes/ñ puede
  mostrarse mal si el archivo es UTF-8 (que es como escriben `read_file`/`write_file`)
  — para LEER contenido de archivos usá esas tools, no `type` vía `run_command`;
  (2) si un `run_command` se corta por timeout, el proceso puede quedar corriendo
  del lado Windows (Win32-OpenSSH no mata el árbol de procesos al cerrar el canal).
- Alcance actual: solo `deep agent`/`deep remote` (no `deep build`).

#### Habilitar SSH en la máquina remota

`deep` se conecta como cualquier cliente SSH — necesitás `sshd` corriendo y tu clave
pública autorizada ahí. Si esa máquina todavía no acepta conexiones SSH:

**Linux** (Debian/Ubuntu; en otras distros cambia el gestor de paquetes):
```bash
sudo apt install openssh-server
sudo systemctl enable --now ssh
```
Después, desde TU máquina (el cliente):
```bash
ssh-copy-id usuario@servidor   # copia tu clave pública, pide el password una sola vez
```

**macOS**: activar "Acceso remoto" (Remote Login) en Preferencias/Configuración del
Sistema → General → Compartir en red — o por línea de comandos:
```bash
sudo systemsetup -setremotelogin on
```
Después, `ssh-copy-id usuario@servidor` igual que en Linux.

**Windows** (PowerShell **como Administrador**, en la máquina remota):
```powershell
# 1. Instalar el server de OpenSSH (una sola vez)
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# 2. Arrancarlo y dejarlo iniciando solo con el sistema
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

# 3. Permitir el puerto 22 en el firewall
New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -DisplayName "OpenSSH Server (sshd)" `
  -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```
Para la clave, **si tu cuenta es Administrador** (algo muy común), Windows usa un
archivo distinto al `~/.ssh/authorized_keys` normal — este paso se olvida seguido y
la clave queda "copiada" pero `sshd` la ignora en silencio:
```powershell
# pegá tu clave pública completa (la de tu MÁQUINA, no la del servidor) acá:
Add-Content -Force -Path "$env:ProgramData\ssh\administrators_authorized_keys" -Value "ssh-ed25519 AAAA... tu@email"

# permisos: sshd rechaza el archivo si no son EXACTAMENTE estos (SID en vez de
# nombre de grupo, para que funcione sin importar el idioma de Windows)
icacls.exe "$env:ProgramData\ssh\administrators_authorized_keys" /inheritance:r
icacls.exe "$env:ProgramData\ssh\administrators_authorized_keys" /grant "*S-1-5-32-544:F"
icacls.exe "$env:ProgramData\ssh\administrators_authorized_keys" /grant "*S-1-5-18:F"

Restart-Service sshd
```
Si tu cuenta NO es Administrador, `~/.ssh/authorized_keys` funciona normal — corré
`ssh-copy-id usuario@servidor` desde tu máquina como en Linux/macOS.

En los tres casos, probá `ssh usuario@servidor` desde tu máquina antes de usar `deep`:
si entra sin pedirte password, ya podés usar `--host`/`deep remote`/`/remote`.

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
| `search_code` | Recuperación por **relevancia** (índice BM25 local, incremental): ubica "dónde se hace X" en codebases grandes y devuelve los fragmentos más pertinentes con `archivo:línea`. Mejor que grep para orientarse. Con `pip install "deepseek-builder[semantic]"` suma búsqueda **semántica** (embeddings locales `fastembed`, score híbrido) que además matchea cross-idioma; sin eso, BM25 puro. |
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
| `/remote` | Conecta la sesión actual a un workspace remoto vía SSH, pidiendo el host y la carpeta paso a paso (sin recordar `--host`). |
| `/disconnect` · `/logout` | Cierra la conexión remota y vuelve a trabajar en el directorio local. |
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

### Idioma del código

Podés describir el proyecto en tu idioma (ej. español) y el agente igual escribe **todo el
código en inglés** por defecto —nombres, comentarios, docstrings, commits—, que es el estándar
y facilita soporte/reventa. Conversa con vos en tu idioma, pero el código va en inglés.

Dos variables de entorno lo controlan, **independientes** entre sí:

| Variable | Controla | Default |
|----------|----------|---------|
| `DEEP_CODE_LANG` | Idioma de los **identificadores** (variables, funciones, clases, archivos, commits/log) | `inglés` |
| `DEEP_COMMENT_LANG` | Idioma de **comentarios y docstrings** | igual que `DEEP_CODE_LANG` |

Así podés tener **código en inglés pero comentarios en español**: `DEEP_COMMENT_LANG=español`.
Los comentarios referencian los identificadores por su nombre real en inglés (no los traducen):
una función `getSeller()` queda con ese nombre, y el comentario en español dice algo como
«`getSeller()` asigna un vendedor en la variable `seller` y lo retorna».

> Si nombrás un archivo explícitamente en otro idioma en el pedido, respeta ese nombre (tu
> instrucción literal manda).

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
  Vela con `/tasks`. Si llega al límite de pasos con tareas pendientes, **auto-reanuda** solo
  (hasta `max_auto_resume` veces) en vez de cortar y pedirte `continuá` a mano.
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
pip install "deepseek-builder[https]"      # trustme, para deep serve --https
pip install "deepseek-builder[semantic]"   # fastembed, búsqueda semántica en search_code
pip install "deepseek-builder[ssh]"        # paramiko, para deep agent --host (workspace remoto)
```

Sin `prompt_toolkit` el REPL funciona igual pero en modo básico. Sin `trustme`, `deep serve --https` muestra un error con las instrucciones de instalación. Sin `fastembed`, `search_code` usa BM25 léxico (igual de útil para identificadores); con él, suma matching semántico cross-idioma. Se puede desactivar con `DEEP_NO_SEMANTIC=1`. Sin `paramiko`, `--host` muestra un error con las instrucciones de instalación.

El modelo de embeddings es configurable con `DEEP_EMBED_MODEL`. El default es English-centric; si hacés consultas en español conviene un modelo multilingüe:

```bash
export DEEP_EMBED_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

(Mejora notablemente el ranking de consultas en español sobre código en inglés.)

---

## Compatibilidad

Funciona en Linux, macOS y Windows 10+ (con secuencias ANSI habilitadas automáticamente).

---

## Changelog

Ver [CHANGELOG.md](doc/CHANGELOG.md) para el detalle de cada versión.

## Philosophy

Ver [PHILOSOPHY.md](doc/PHILOSOPHY.md).

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
