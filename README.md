# deep

CLI/REPL para generar proyectos completos usando la API de DeepSeek. Le das una descripción en lenguaje natural y genera los archivos, los evalúa, y aprende de cada ejecución para mejorar las siguientes.

## Instalación

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/cynchro/deepseekCLI/main/install.sh)
```

O desde el repositorio clonado:

```bash
git clone https://github.com/cynchro/deepseekCLI.git
cd deepseekCLI
bash install.sh
```

La primera vez que ejecutes `deep`, te va a pedir la API key y la guardará automáticamente en `~/.config/deep/config.json`. Obtené tu key en [platform.deepseek.com](https://platform.deepseek.com/api_keys).

Para actualizarla más adelante:

```bash
deep config set-key
```

Si preferís usar una variable de entorno (tiene prioridad sobre el archivo de config):

```bash
export DEEPSEEK_API_KEY=tu_key_aqui
```

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

## Comandos

### `build` — Genera un proyecto

```bash
deep build "descripción del proyecto"
deep build "app Flask con SQLite" -f              # corrige automáticamente si falla
deep build "landing page en HTML/CSS" -o ~/dir   # especifica directorio de salida
deep build "compilador de expresiones" --model deepseek-reasoner
```

### `ask` — Conversación con el modelo

```bash
deep ask "cómo funciona Redis?"
```

Dentro del REPL, `ask` inicia una nueva conversación. El prompt cambia a `chat ❯` y podés seguir preguntando sin repetir el comando:

```
deep ❯ ask qué es Redis?
...respuesta...

chat ❯ es necesario dockerizarlo?    ← sigue el hilo automáticamente
...respuesta contextual...

chat ❯ ask qué es Kafka?             ← ask resetea e inicia nueva conversación
```

### `update` — Modifica un proyecto existente

```bash
deep update "agregá autenticación JWT"
deep update "agregá tests unitarios" --model deepseek-reasoner
```

Modifica los archivos del proyecto en el directorio actual sin tener que regenerarlo desde cero.

### `fix` — Corrige errores del proyecto actual

```bash
deep fix
```

Usa el contexto guardado en `.deep/` para corregir el proyecto sin necesidad de volver a describir la tarea.

### `show` — Muestra el contexto del proyecto actual

```bash
deep show
```

Muestra la tarea original, el modelo usado, el plan, los archivos generados y el resultado de la evaluación.

### `doctor` — Diagnóstico del entorno

```bash
deep doctor
```

Verifica Python, API key, conexión con DeepSeek, dependencias y configuración del PATH.

### `upgrade` — Actualiza el CLI

```bash
deep upgrade
```

Descarga e instala la última versión desde GitHub sin necesidad de reinstalar manualmente.

### `balance` / `history` / `config`

```bash
deep balance            # muestra el crédito disponible en DeepSeek
deep history            # muestra las experiencias acumuladas de builds anteriores
deep config             # muestra la API key guardada
deep config set-key     # guarda una nueva API key
```

## Cómo funciona `build`

Cada `deep build` ejecuta 5 fases:

1. **Planificación** — diseña la arquitectura del proyecto
2. **Generación** — escribe el código completo
3. **Escritura** — guarda los archivos en disco
4. **Evaluación** — revisa si el resultado cumple con la tarea
5. **Aprendizaje** — guarda la experiencia para mejorar builds futuros

Si la evaluación falla, `deep` te pregunta si querés corregirlo automáticamente (o usá `-f` para que lo haga sin preguntar).

## Reglas personalizadas (.deeprules)

Podés definir restricciones que DeepSeek debe respetar en cada `build` y `update`. Crea un archivo `.deeprules` en tu directorio:

```bash
cp .deeprules.example .deeprules
```

Ejemplo de `.deeprules`:

```
usa principios SOLID
no hardcodees credenciales
separá la lógica de negocio de los controladores
```

Las reglas se cargan automáticamente si el archivo existe en el directorio actual.

## Requisitos

- Python 3.9+
- API key de DeepSeek

## Dependencias opcionales

```bash
pip install prompt_toolkit   # activa autocompletado e historial en el REPL
```

Sin `prompt_toolkit` el REPL funciona igual pero en modo básico.

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
