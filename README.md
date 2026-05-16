# deep

CLI/REPL para generar proyectos completos usando la API de DeepSeek. Le das una descripción en lenguaje natural y genera los archivos, los evalúa, y aprende de cada ejecución para mejorar las siguientes.

## Instalación

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/cynchro/deepseekCLI/main/install.sh)
```

O desde el repositorio clonado:

```bash
git clone https://github.com/cynchro/deepseekCLI.git
cd deepseekcli
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

```
deep ❯ build una API REST en FastAPI con autenticación JWT
deep ❯ fix
deep ❯ balance
deep ❯ history
```

### Modo directo (scripting)

```bash
# Genera un proyecto en el directorio actual
deep build "API REST en FastAPI con autenticación JWT"

# Genera y corrige automáticamente si la evaluación falla
deep build "app Flask con SQLite" -f

# Especifica el directorio de salida
deep build "landing page en HTML/CSS" -o ~/proyectos/landing

# Usa deepseek-reasoner para tareas complejas
deep build "compilador de expresiones matemáticas" --model deepseek-reasoner

# Muestra el crédito disponible
deep balance

# Muestra el historial de proyectos generados
deep history

# Muestra la API key guardada
deep config

# Actualiza la API key
deep config set-key
```

## Cómo funciona

Cada `deep build` ejecuta 5 fases:

1. **Planificación** — diseña la arquitectura del proyecto
2. **Generación** — escribe el código completo
3. **Escritura** — guarda los archivos en disco
4. **Evaluación** — revisa si el resultado cumple con la tarea
5. **Aprendizaje** — guarda la experiencia para mejorar builds futuros

Si la evaluación falla, `deep` te pregunta si querés corregirlo automáticamente (o usá `-f` para que lo haga sin preguntar).

## Reglas personalizadas (.deeprules)

Podés definir restricciones que DeepSeek debe respetar en cada build. Crea un archivo `.deeprules` en tu directorio:

```bash
cp .deeprules.example .deeprules
```

Ejemplo de `.deeprules`:

```
usa principios SOLID
no hardcodees credenciales
separá la lógica de negocio de los controladores
```

Las reglas se cargan automáticamente si el archivo existe en el directorio actual o en el directorio de salida del proyecto.

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

El comando `fix` usa ese contexto para corregir el proyecto sin tener que volver a describir la tarea.
