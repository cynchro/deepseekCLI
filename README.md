# deep

CLI/REPL para generar proyectos completos usando la API de DeepSeek. Le das una descripción en lenguaje natural y genera los archivos, los evalúa, y aprende de cada ejecución para mejorar las siguientes.

## Instalación

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
deep build "app Flask con SQLite" -f              # corrige automáticamente si falla
deep build "landing page en HTML/CSS" -o ~/dir   # especifica directorio de salida
deep build "compilador de expresiones" --model deepseek-reasoner
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

> **Requiere `trustme`:** `pip install trustme` o `pip install "deepseekcli[https]"`

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
pip install "deepseekcli[https]"    # instala trustme junto con el paquete
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
