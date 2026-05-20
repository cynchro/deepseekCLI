# deep

<a href="https://github.com/cynchro/deepseekCLI"><img src="https://img.shields.io/github/stars/cynchro/deepseekCLI?style=social" alt="GitHub stars"/></a>
<a href="https://pypi.org/project/deepseek-builder/"><img src="https://img.shields.io/pypi/v/deepseek-builder" alt="PyPI version"/></a>
<a href="https://pypi.org/project/deepseek-builder/"><img src="https://img.shields.io/pypi/dm/deepseek-builder" alt="PyPI downloads"/></a>

CLI/REPL para generar proyectos completos usando la API de DeepSeek. Le das una descripción en lenguaje natural y genera los archivos, los evalúa, y aprende de cada ejecución para mejorar las siguientes.

Hecho con ❤️ por [Cynchro Labs](https://www.cynchrolabs.com.ar)

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

### REPL interactivo

```bash
deep
```

Abre un REPL con autocompletado e historial. Desde ahí podés usar todos los comandos.

### Modo directo (scripting)

Todos los comandos también funcionan directamente desde la terminal:

```bash
deep build "API REST en FastAPI con autenticación JWT"
deep ask "cómo funciona Redis?"
deep doctor
```

---

## Comandos

### `build` — Genera un proyecto

```bash
deep build "descripción del proyecto"
deep build -t tarea.txt                          # carga la descripción desde un archivo
deep build "app Flask con SQLite" -f              # corrige automáticamente si falla
deep build "landing page en HTML/CSS" -o ~/dir   # especifica directorio de salida
deep build "compilador de expresiones" --model deepseek-reasoner
```

También podés combinar `-t` con otras opciones:

```bash
deep build -t tarea.txt -f --model deepseek-reasoner -o ~/proyectos
```

El archivo puede ser cualquier `.txt` con la descripción en lenguaje natural. En el REPL:

```
deep ❯ build -t /ruta/mi_tarea.txt
deep ❯ build -t tarea.txt -f
```

Cada `build` ejecuta 5 fases:

1. **Planificación** — diseña la arquitectura usando experiencias previas similares
2. **Generación** — escribe el código completo
3. **Escritura** — guarda los archivos en disco
4. **Evaluación** — revisa si el resultado cumple con la tarea
5. **Aprendizaje** — guarda la experiencia para informar builds futuros

Si la evaluación falla, `deep` te pregunta si querés corregirlo (o usá `-f` para que lo haga sin preguntar).

---

### `ask` — Conversación con el modelo

```bash
deep ask "cómo funciona Redis?"
```

Dentro del REPL, `ask` inicia una conversación. El prompt cambia a `chat ❯` y podés seguir preguntando sin repetir el comando:

```
deep ❯ ask qué es Redis?
...respuesta...

chat ❯ es necesario dockerizarlo?    ← continúa el hilo automáticamente
...respuesta contextual...

chat ❯ ask qué es Kafka?             ← ask resetea e inicia nueva conversación
```

Cuando la conversación se acerca al límite de contexto del modelo, `deep` la compacta automáticamente:

```
⚡ Compactando conversación…
```

Esto resume los mensajes anteriores para que la conversación pueda continuar indefinidamente sin perder el hilo.

Para reiniciar la conversación manualmente:

```
chat ❯ reset
```

---

### `update` — Modifica un proyecto existente

```bash
deep update "agregá autenticación JWT"
deep update "agregá tests unitarios" --model deepseek-reasoner
```

Modifica los archivos del proyecto en el directorio actual sin tener que regenerarlo desde cero.

---

### `fix` — Corrige errores del proyecto actual

```bash
deep fix
```

Usa el contexto guardado en `.deep/` para corregir el proyecto sin necesidad de volver a describir la tarea.

---

### `show` — Muestra el contexto del proyecto actual

```bash
deep show
```

Muestra la tarea original, el modelo usado, el plan, los archivos generados y el resultado de la evaluación.

---

### `serve` — Servidor web para usar deep desde el celular

```bash
deep serve              # HTTP básico
deep serve --https      # HTTPS + instalable como app
deep serve --port 9000 --https  # puerto personalizado con HTTPS
```

Levanta una interfaz web accesible desde cualquier dispositivo en la red.

---

#### Recomendación: usá Tailscale para conectar el celular

[Tailscale](https://tailscale.com) es la forma más cómoda y segura de acceder a `deep serve` desde el celular, incluso si estás en redes distintas (datos móviles, otra WiFi, etc.).

**Por qué Tailscale:**
- Te asigna una IP fija (`100.x.x.x`) que no cambia aunque cambies de red
- Funciona sin abrir puertos en el router
- La URL es siempre la misma, sin tener que buscar la IP local cada vez
- Sin Tailscale, el celular y la computadora tienen que estar en la misma WiFi

**Setup (una sola vez):**

1. Instalá Tailscale en la compu: [tailscale.com/download](https://tailscale.com/download)
2. Instalá Tailscale en el celular (App Store / Play Store)
3. Logueate con la misma cuenta en ambos
4. Listo — la compu aparece en la red Tailscale con una IP `100.x.x.x`

Con Tailscale activo, `deep serve --https` muestra directamente la URL `100.x.x.x` para usar desde el celular.

---

#### Instalar como app en el celular (PWA)

Para que el celular pueda instalar `deep` como app nativa, la conexión tiene que ser HTTPS. `deep serve --https` genera el certificado automáticamente.

> **Requiere `trustme`:** `pip install trustme` o `pip install "deepseek-builder[https]"`

**Primera vez — instalación del certificado (una sola vez por dispositivo):**

```
$ deep serve --https

  🔐 HTTPS activado

  Paso 1 — Instalá el certificado CA en tu celular (una sola vez):
     http://100.x.x.x:8001    ← abrí esta URL en el celular

     Android : Ajustes → Seguridad → Instalar certificado → CA certificate
     iOS     : Abrir archivo descargado → Ajustes → General →
               VPN y administración del dispositivo → Instalar → Confiar

  Paso 2 — Abrí la app e instalala:
     https://100.x.x.x:8000   ← abrí esta URL en el celular
```

**Pasos:**

1. Abrí la URL del **Paso 1** en el navegador del celular
2. Descargá el archivo `.pem` y seguí las instrucciones según tu sistema:
   - **Android:** Ajustes → Seguridad → Cifrado y credenciales → Instalar un certificado → Certificado de CA
   - **iOS:** Al abrir el archivo, aparece "Perfil descargado" → Ajustes → General → VPN y administración → Instalar → Confiar en el certificado raíz
3. Abrí la URL del **Paso 2** en el navegador — aparece el botón **⬇** en la cabecera
4. Tap en **⬇** → la app se instala como si fuera nativa

A partir de ese momento no necesitás repetir el proceso. Solo `deep serve --https` y abrís la app instalada directamente desde el home del celular.

> **Nota:** El certificado autofirmado es local y temporal — es solo para que el navegador acepte HTTPS en tu red privada. No sale a internet.

---

### `doctor` — Diagnóstico del entorno

```bash
deep doctor
```

Verifica Python, API key, conexión con DeepSeek, dependencias y configuración del PATH. Funciona correctamente en Linux, macOS y Windows.

---

### `upgrade` — Actualiza el CLI

```bash
deep upgrade
```

Descarga e instala la última versión desde GitHub sin necesidad de reinstalar manualmente.

---

### `balance` / `history` / `config`

```bash
deep balance            # muestra el crédito disponible en DeepSeek
deep history            # muestra las experiencias acumuladas de builds anteriores
deep config             # muestra la API key guardada
deep config set-key     # guarda una nueva API key
```

---

## Debug

El flag `--debug` activa un log detallado de todo lo que hace `deep` durante una ejecución: prompts enviados, respuestas del modelo, tokens usados, latencias, archivos escritos y cada fase del pipeline. Se guarda en `debug.log` en el directorio donde corras el comando.

### Activación

`--debug` va siempre **antes** del subcomando:

```bash
deep --debug build "mi tarea"
deep --debug build -t tarea.txt
deep --debug build -t tarea.txt -f --model deepseek-reasoner
deep --debug ask "cómo funciona Redis?"
deep --debug update "agregá tests"
deep --debug fix
```

También podés activarlo con una variable de entorno (útil para scripts):

```bash
DEEP_DEBUG=1 deep build -t tarea.txt
```

### Debug con archivo de tarea

La combinación más común para analizar un build completo:

```bash
# 1. Escribís la tarea en un .txt (sin límite de largo)
cat tarea.txt

# 2. Corrés con debug
deep --debug build -t tarea.txt

# 3. Analizás el log mientras corre o al terminar
tail -f debug.log          # seguir en tiempo real
cat debug.log              # ver todo al terminar
grep '\[API_OK\]' debug.log        # solo latencias y tokens
grep '\[PHASE\]' debug.log         # solo transiciones de fase
grep '\[WRITER\]' debug.log        # solo archivos escritos
grep '\[EVAL\]' debug.log          # solo el resultado de evaluación
```

Podés combinar todos los flags normales con `--debug`:

```bash
deep --debug build -t tarea.txt -f -o ~/proyectos --model deepseek-reasoner
```

### Estructura del log

Cada línea tiene el formato:

```
[HH:MM:SS.mmm  + elapsed] [TAG             ] mensaje
```

- `HH:MM:SS.mmm` — hora del evento con milisegundos
- `+elapsed` — segundos desde que arrancó la sesión (para medir duración de cada paso)
- `TAG` — identificador de la sección (ver tabla abajo)

Los bloques de texto largo (prompts, respuestas) se muestran indentados:

```
[07:32:11.450  +   0.00s] [API_CALL        ] model=deepseek-chat  temp=0.5  max_tokens=1000
[07:32:11.451  +   0.01s] [API_SYS         ] ── system_prompt ──────────────────────────────
  Eres un arquitecto de software senior. Creas planes claros y accionables.
  ────────────────────────────────────────────────────────────
[07:32:11.452  +   0.02s] [API_USER        ] ── user_prompt ──────────────────────────────
  Crea un plan detallado para:
  API REST en FastAPI con JWT y PostgreSQL
  ...
  ────────────────────────────────────────────────────────────
[07:32:13.210  +   1.76s] [API_OK          ] attempt=1  latency=1.76s  tokens_in=320  tokens_out=580  total=900
[07:32:13.211  +   1.77s] [API_RESP        ] ── response_content ──────────────────────────────
  ## Plan
  1. Estructura de carpetas: app/, tests/, ...
  ...
  ────────────────────────────────────────────────────────────
```

### Tags del log

| Tag | Qué registra |
|-----|-------------|
| `INIT` | Comando completo con el que arrancó `deep` |
| `PHASE` | Transición de fase (1 planificación → 5 aprendizaje) |
| `API_CALL` | Antes de cada llamada: modelo, temperatura, max_tokens |
| `API_SYS` | System prompt completo enviado al modelo |
| `API_USER` | User prompt completo enviado al modelo |
| `API_OK` | Resultado: intento, latencia, tokens in/out/total |
| `API_RESP` | Respuesta completa del modelo |
| `API_ERR` | Error en un intento (incluye reintentos automáticos) |
| `PLAN` | Experiencias similares encontradas antes de planificar |
| `PHASE_1` | Plan generado por el modelo |
| `PHASE_2` | Tokens usados en la generación de código |
| `PHASE_3` | Archivos escritos en disco |
| `PHASE_4` | Resultado de la evaluación |
| `PHASE_5` | Análisis de experiencia guardado en memoria |
| `PHASE_6` | Reflexión profunda (si `reflect=True`) |
| `EVAL` | JSON de evaluación parseado (score, issues, positives) |
| `WRITER` | Directorio del proyecto, bloques detectados, cada archivo |
| `EXEC` | Tokens usados en la fase de ejecución |
| `FIX` | Flujo de corrección automática (`fix`, `build -f`) |
| `UPDATE` | Flujo de modificación de proyecto existente |
| `SYSTEM` | Resumen final del ciclo completo |

### Queries útiles para analizar el log

```bash
# Cuántas llamadas a la API y tokens totales
grep 'API_OK' debug.log

# Ver solo los archivos que se escribieron
grep '→' debug.log

# Ver si hubo errores o reintentos
grep 'API_ERR' debug.log

# Ver el resultado de la evaluación
grep -A 20 '\[EVAL\]' debug.log

# Medir cuánto tardó cada fase
grep -E '\[PHASE\]|\[PHASE_[1-8]\]' debug.log

# Ver si el modelo encontró experiencias previas similares
grep '\[PLAN\]' debug.log

# Seguir el log en tiempo real mientras corre el build
tail -f debug.log
```

### Notas

- El log se **agrega** al final del archivo (no sobreescribe). Cada sesión empieza con una línea `SESSION ...` para distinguirlas.
- Para empezar limpio antes de un debug: `rm debug.log`
- El archivo puede crecer rápido si los prompts/respuestas son largos. Un `build` típico genera entre 200 y 500 líneas.
- Para compartir el log o analizarlo después: el archivo es texto plano, se puede abrir con cualquier editor.

---

## Reglas personalizadas (.deeprules)

Podés definir restricciones que DeepSeek debe respetar en cada `build`, `update` y `fix`. Creá un archivo `.deeprules` en la raíz de tu proyecto:

```
# .deeprules
Usar PostgreSQL, nunca SQLite
Todo el código fuente en inglés
Sin dependencias externas que no sean del stdlib
Separar rutas, modelos y servicios en archivos distintos
```

Las líneas que empiezan con `#` son comentarios y se ignoran. Las reglas se cargan automáticamente si el archivo existe en el directorio actual.

Hay un ejemplo completo en [`examples/deeprules.example`](examples/deeprules.example).

---

## Skills

Los skills son **roles especializados** para el comando `ask`. A diferencia de las `.deeprules` (que restringen el *output* del código), un skill cambia *cómo responde* el modelo durante una conversación.

### Usar un skill

```
deep ❯ skill list
   📦 Skills disponibles:
      reviewer         Code review estricto como senior developer
      security         Análisis de seguridad — OWASP, vulnerabilidades, hardening
      docs             Genera documentación técnica clara y concisa
      explainer        Explica código o conceptos técnicos de forma simple
      refactor         Refactoriza código manteniendo el comportamiento

deep ❯ reviewer esta función tiene race conditions?
   → abre conversación con el rol de reviewer

chat ❯ y si agregara un lock aquí...   ← continúa con el mismo rol

deep ❯ reset                            ← nueva conversación
```

El nombre del skill se usa directamente como comando. Cambiar de skill reinicia la conversación automáticamente.

### Crear un skill

Interactivo:

```
deep ❯ skill new
  Nombre del skill: traductor
  Descripción breve: Traduce documentación técnica al español
  System prompt (terminá con una línea que solo diga FIN):
  Sos un traductor técnico experto...
  FIN
  ¿Local al proyecto? [s/N]: n
  ✅ Skill 'traductor' guardado en ~/.config/deep/skills/traductor.skill
```

O creando el archivo directamente en `~/.config/deep/skills/`:

```
# ~/.config/deep/skills/reviewer.skill
description: Code review estricto como senior developer
temperature: 0.2
max_tokens: 3000
---
Sos un senior developer con 15 años de experiencia revisando código de otros.
Tu trabajo es encontrar problemas reales, no halagos.
...
```

### Skills globales vs. de proyecto

| Ubicación | Alcance |
|-----------|---------|
| `~/.config/deep/skills/` | Disponibles desde cualquier directorio |
| `.deep/skills/` | Solo en el proyecto actual |

Los skills de proyecto se cargan además de los globales y tienen prioridad si hay un nombre repetido.

Hay ejemplos listos para usar en [`examples/skills/`](examples/skills/).

---

## Estructura del proyecto generado

Cada proyecto generado incluye una carpeta `.deep/` con metadatos:

```
mi-proyecto/
├── .deep/
│   ├── context.json      # tarea, modelo y plan usado
│   ├── evaluation.json   # resultado de la evaluación
│   └── RESPONSE.md       # respuesta completa del modelo
└── ... archivos del proyecto
```

Los comandos `fix`, `update` y `show` usan ese contexto automáticamente.

---

## Requisitos

- Python 3.9+
- API key de DeepSeek

### Dependencias opcionales

```bash
pip install prompt_toolkit          # autocompletado e historial en el REPL
pip install trustme                 # HTTPS para instalar la app en el celular
pip install "deepseek-builder[https]"    # instala trustme junto con el paquete
```

Sin `prompt_toolkit` el REPL funciona igual pero en modo básico (sin autocompletado). Sin `trustme`, `deep serve --https` muestra un error con las instrucciones de instalación.

---

## Compatibilidad

| Sistema | Estado |
|---------|--------|
| Linux | ✅ Completo |
| macOS | ✅ Completo |
| Windows 10+ (Windows Terminal) | ✅ Completo |
| Windows (cmd.exe) | ⚠️ Funcional, sin colores |
| WSL | ✅ Completo |

---

## Philosophy

See [PHILOSOPHY.md](PHILOSOPHY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## Contact

**alexissaucedo@gmail.com** · [cynchrolabs.com.ar](https://www.cynchrolabs.com.ar)

## Buy me a coffee?

If `deep` saved you time, consider a donation — it helps keep the project going.

<a href="https://www.paypal.com/donate/?hosted_button_id=YX332RT7KSJ4Q">
  <img src="https://img.shields.io/badge/PayPal-Donate-blue?logo=paypal" alt="Donate with PayPal"/>
</a>

---

⭐ If you like this project, give it a star!

<a href="https://github.com/cynchro/deepseekCLI">
  <img src="https://img.shields.io/github/stars/cynchro/deepseekCLI?style=social" alt="GitHub stars"/>
</a>
