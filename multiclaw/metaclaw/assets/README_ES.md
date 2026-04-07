<div align="center">

<img src="new_logo2.png" alt="MetaClaw" width="600">

<br/>

# Habla con tu agente — aprende y *EVOLUCIONA*.

<p>Inspirado en cómo aprende el cerebro. Meta-aprende y evoluciona tu 🦞 con cada conversación. Sin GPU. Compatible con Kimi, Qwen, Claude, MiniMax y más.</p>

<img src="metaclaw_mainfig_v2.png" alt="MetaClaw Architecture" width="800">

<p>
  <a href="https://github.com/aiming-lab/MetaClaw"><img src="https://img.shields.io/badge/github-MetaClaw-181717?style=flat&labelColor=555&logo=github&logoColor=white" alt="GitHub"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=flat&labelColor=555" alt="License MIT"></a>
  <img src="https://img.shields.io/badge/⚡_Totalmente_Asíncrono-yellow?style=flat&labelColor=555" alt="Fully Async" />
  <img src="https://img.shields.io/badge/☁️_Sin_cluster_GPU-blue?style=flat&labelColor=555" alt="No GPU Cluster" />
  <img src="https://img.shields.io/badge/🛠️_Evolución_de_skills-orange?style=flat&labelColor=555" alt="Skill Evolution" />
  <img src="https://img.shields.io/badge/🚀_Despliegue_en_un_clic-green?style=flat&labelColor=555" alt="One-Click Deploy" />
</p>

<br/>

[🇺🇸 English](../README.md) • [🇨🇳 中文](./README_ZH.md) • [🇯🇵 日本語](./README_JA.md) • [🇰🇷 한국어](./README_KO.md) • [🇫🇷 Français](./README_FR.md) • [🇩🇪 Deutsch](./README_DE.md) • [🇧🇷 Português](./README_PT.md) • [🇷🇺 Русский](./README_RU.md) • [🇮🇹 Italiano](./README_IT.md) • [🇻🇳 Tiếng Việt](./README_VI.md) • [🇦🇪 العربية](./README_AR.md) • [🇮🇳 हिन्दी](./README_HI.md)

<br/>

[Descripcion](#-descripción) • [Inicio rapido](#-inicio-rápido) • [Configuracion](#️-configuración) • [Modo Skills](#-modo-skills) • [Modo RL](#-modo-rl) • [Modo Auto](#-modo-auto-por-defecto) • [Cita](#-cita)

</div>

---

<div align="center">

### Dos comandos. Eso es todo.
</div>

```bash
metaclaw setup              # asistente de configuración inicial
metaclaw start              # por defecto: modo auto, skills + entrenamiento RL programado
metaclaw start --mode rl    # RL sin planificador (entrena inmediatamente al llenar batch)
metaclaw start --mode skills_only  # solo skills, sin RL (no requiere Tinker)
```

<div align="center">
<img src="metaclaw.gif" alt="MetaClaw demo" width="700">
</div>

---

## 🔥 Noticias

- **[25/03/2026]** **v0.4.0** — Contexture layer: MetaClaw ahora persiste la memoria entre sesiones para usuarios y proyectos. Los hechos relevantes, preferencias e historial del proyecto se recuperan automáticamente y se inyectan en los prompts. Incluye política de memoria adaptativa, consolidación en segundo plano y un servicio sidecar de memoria opcional.
- **[16/03/2026]** **v0.3.2** Soporte multi-Claw: IronClaw, PicoClaw, ZeroClaw, CoPaw, NanoClaw y NemoClaw ahora son compatibles junto con OpenClaw. NanoClaw a través del nuevo endpoint compatible con Anthropic `/v1/messages`; NemoClaw a través del enrutamiento de inferencia OpenShell. OpenRouter agregado como plataforma LLM.
- **[13/03/2026]** **v0.3.1** Soporte de backend MinT: el entrenamiento RL ahora funciona con Tinker y MinT. Configurable via `rl.backend` (auto/tinker/mint).
- **[13/03/2026]** **v0.3** Soporte de meta-aprendizaje continuo: las actualizaciones RL solo se ejecutan durante horas de sueño, periodos de inactividad o reuniones de Google Calendar. Se agrega separación de conjuntos support/query para evitar que señales de recompensa obsoletas contaminen las actualizaciones del modelo.
- **[11/03/2026]** **v0.2** Despliegue en un clic mediante la CLI `metaclaw`. Skills activados por defecto, RL ahora es opcional.
- **[09/03/2026]** Lanzamos **MetaClaw**. Habla con tu agente y deja que evolucione automáticamente. **Sin** necesidad de despliegue de GPU; conéctate directamente a la **API**.

---

## 🎥 Demo

https://github.com/user-attachments/assets/d86a41a8-4181-4e3a-af0e-dc453a6b8594

---

## 📖 Descripción

**MetaClaw es un agente que meta-aprende y evoluciona en entornos reales.**
Habla con tu agente como de costumbre. MetaClaw convierte cada conversación en vivo en una señal de aprendizaje, permitiendo que el agente mejore continuamente a través del despliegue real en lugar de depender únicamente del entrenamiento offline.

Internamente, envuelve tu modelo detrás de un proxy compatible con OpenAI (con un endpoint compatible con Anthropic `/v1/messages` para agentes como NanoClaw), intercepta interacciones desde OpenClaw, NanoClaw, NemoClaw y otros agentes compatibles, inyecta skills relevantes en cada turno y meta-aprende de la experiencia acumulada. Las skills se resumen automáticamente tras cada sesión; con RL activado, un planificador de meta-aprendizaje posterga las actualizaciones de pesos a ventanas de inactividad para no interrumpir al agente durante el uso activo.

No se necesita cluster GPU. MetaClaw funciona con cualquier API de LLM compatible con OpenAI y usa un backend compatible con Tinker para entrenamiento LoRA en la nube. [Tinker](https://www.thinkingmachines.ai/tinker/) es la ruta de referencia por defecto; si hace falta, MinT o Weaver pueden habilitarse mediante paquetes de compatibilidad separados.

## 🤖 Características principales

### **Despliegue en un clic**
Configura una vez con `metaclaw setup`, luego `metaclaw start` levanta el proxy, inyecta skills y conecta OpenClaw automáticamente. Sin necesidad de scripts de shell manuales.

### **Tres modos de operación**

| Modo | Por defecto | Función |
|------|------------|---------|
| `skills_only` | | Proxy para tu API LLM. Skills inyectados, resumidos automáticamente tras cada sesión. Sin GPU/Tinker requerido. |
| `rl` | | Skills + entrenamiento RL (GRPO). Entrena inmediatamente cuando un batch está lleno. OPD opcional para destilación de profesor. |
| `auto` | ✅ | Skills + RL + planificador inteligente. Actualizaciones de pesos RL solo durante ventanas de sueño/inactividad/reunión. |

### **Memoria a largo plazo**
MetaClaw puede conservar hechos, preferencias e historial del proyecto entre sesiones e inyectar contexto relevante en cada turno — así tu agente recuerda lo que le dijiste, incluso semanas después.

### **Asíncrono por diseño**
El serving, el modelado de recompensas y el entrenamiento están completamente desacoplados. El agente continúa respondiendo mientras el scoring y la optimización se ejecutan en paralelo.

---

## 🚀 Inicio rápido

### 1. Instalación

**OpenClaw (instalación en un clic):** usa el lanzamiento [v0.4.0](https://github.com/aiming-lab/MetaClaw/releases/tag/v0.4.0) — ejecuta los comandos de abajo, luego `metaclaw setup` y `metaclaw start`. Más detalle (Windows, espejos, configuración, solución de problemas): [`extensions/metaclaw-openclaw/README.md`](../extensions/metaclaw-openclaw/README.md).

```bash
curl -LO https://github.com/aiming-lab/MetaClaw/releases/download/v0.4.0/metaclaw-plugin.zip
unzip metaclaw-plugin.zip -d ~/.openclaw/extensions
openclaw plugins enable metaclaw-openclaw && openclaw gateway restart
```

**pip** (PyPI o este repositorio):

```bash
pip install -e .                        # modo skills_only (ligero)
pip install -e ".[rl]"                  # + soporte de entrenamiento RL (torch, transformers, tinker)
pip install -e ".[evolve]"              # + evolución de skills via LLM compatible con OpenAI
pip install -e ".[scheduler]"           # + integración Google Calendar para planificador
pip install -e ".[rl,evolve,scheduler]" # recomendado: configuración completa RL + planificador
```
(Opcional) La integración de WeChat utiliza el plugin oficial @tencent-weixin/openclaw-weixin. MetaClaw lo instala automáticamente cuando WeChat está habilitado:

```bash
metaclaw config wechat.enabled true
metaclaw start
```

El plugin se instala automáticamente al iniciar MetaClaw. También puedes instalarlo manualmente:

```bash
npx -y @tencent-weixin/openclaw-weixin-cli@latest install
```

Para cambiar cuentas de WeChat (vuelva a iniciar sesión con un nuevo código QR):

```bash
metaclaw start --wechat-relogin
```

Si quieres usar `rl.backend=mint`, instala el paquete de compatibilidad de MinT por separado en el mismo entorno, por ejemplo [`mindlab-toolkit`](https://github.com/MindLab-Research/mindlab-toolkit). Para `rl.backend=weaver`, instala por separado [`nex-weaver`](https://github.com/nex-agi/weaver). MetaClaw mantiene estas dependencias fuera del paquete por defecto para que los usuarios de RL elijan explícitamente entre Tinker, MinT y Weaver.

### 2. Configuración

```bash
metaclaw setup
```

El asistente interactivo te pedirá:
1. **Elegir tu agente personal** — `openclaw`, `copaw`, `ironclaw`, `picoclaw`, `zeroclaw`, `nanoclaw`, `nemoclaw` o `none` (MetaClaw lo configurará al iniciar)
2. **Elegir tu proveedor LLM** — Kimi, Qwen, OpenAI, Volcano Engine o personalizado
3. **Introducir tu clave API** y opcionalmente activar el entrenamiento RL

La ruta RL de MetaClaw puede cambiar explícitamente entre `tinker`, `mint` y `weaver`. `auto` es el valor recomendado y seguirá infiriendo MinT o Weaver a partir de credenciales o base URLs correspondientes cuando los paquetes estén instalados.

**Tinker**:

```bash
metaclaw config rl.backend tinker
metaclaw config rl.api_key sk-...
metaclaw config rl.model moonshotai/Kimi-K2.5
```

**MinT**:

```bash
metaclaw config rl.backend mint
metaclaw config rl.api_key sk-mint-...
metaclaw config rl.base_url https://mint.macaron.xin/
metaclaw config rl.model Qwen/Qwen3-4B-Instruct-2507
```

**Weaver**:

```bash
metaclaw config rl.backend weaver
metaclaw config rl.api_key sk-...
metaclaw config rl.base_url https://weaver-console.nex-agi.cn
metaclaw config rl.model Qwen/Qwen3-8B
```

Los alias heredados `rl.tinker_api_key` y `rl.tinker_base_url` siguen siendo válidos por compatibilidad.

### 3. Inicio

```bash
metaclaw start
```

Listo. MetaClaw inicia el proxy, configura automáticamente el agente personal elegido y reinicia la puerta de enlace. Abre tu agente y chatea: las skills se inyectan en cada turno y la sesión se resume automáticamente en nuevas skills al terminar.

---

## ⚙️ Configuración

La configuración se encuentra en `~/.metaclaw/config.yaml`, creada por `metaclaw setup`.

**Comandos CLI:**

```
metaclaw setup                  # Asistente de configuración inicial interactivo
metaclaw start                  # Iniciar MetaClaw (por defecto: modo auto)
metaclaw start --mode rl        # Forzar modo RL para esta sesión (sin planificador)
metaclaw start --mode skills_only  # Forzar modo solo skills para esta sesión
metaclaw stop                   # Detener una instancia de MetaClaw en ejecución
metaclaw status                 # Verificar estado del proxy, modo en ejecución y planificador
metaclaw config show            # Ver configuración actual
metaclaw config KEY VALUE       # Establecer un valor de configuración
metaclaw config llm.oauth_token TOKEN               # Guardar token OAuth para el proveedor CLI actual
metaclaw auth paste-token --provider anthropic      # Guardar token OAuth (anthropic | openai-codex | gemini)
metaclaw auth status                                # Mostrar todos los perfiles de autenticación guardados
metaclaw uninstall              # Eliminar todos los datos de MetaClaw, extension OpenClaw y paquete pip
```

Use `metaclaw status` para verificar la disponibilidad y `metaclaw stop` para detener el proceso.

<details>
<summary><b>Referencia completa de configuración (clic para expandir)</b></summary>

```yaml
mode: auto                 # "auto" | "rl" | "skills_only"
claw_type: openclaw        # "openclaw" | "copaw" | "ironclaw" | "picoclaw" | "zeroclaw" | "nanoclaw" | "nemoclaw" | "hermes" | "none"

llm:
  auth_method: api_key      # "api_key" | "oauth_token"
  provider: kimi            # kimi | qwen | openai | minimax | novita | openrouter | volcengine | custom
  model_id: moonshotai/Kimi-K2.5
  api_base: https://api.moonshot.cn/v1
  api_key: sk-...
  # ejemplo oauth_token (token almacenado con `metaclaw auth paste-token`):
  # auth_method: oauth_token
  # provider: anthropic     # anthropic | openai-codex | gemini
  # model_id: claude-sonnet-4-6

proxy:
  port: 30000
  api_key: ""              # bearer token opcional para el proxy local de MetaClaw

skills:
  enabled: true
  dir: ~/.metaclaw/skills   # tu biblioteca de skills
  retrieval_mode: template  # template | embedding
  top_k: 6
  task_specific_top_k: 10   # límite de skills específicos de tarea (por defecto 10)
  auto_evolve: true         # resumir skills automáticamente tras cada sesión

rl:
  enabled: false            # poner a true para activar entrenamiento RL
  backend: auto             # "auto" | "tinker" | "mint" | "weaver"
  model: moonshotai/Kimi-K2.5
  api_key: ""
  base_url: ""              # endpoint opcional del backend, p. ej. https://mint.macaron.xin/ para MinT o https://weaver-console.nex-agi.cn para Weaver
  tinker_api_key: ""        # alias heredado de api_key
  tinker_base_url: ""       # alias heredado de base_url
  prm_url: https://api.openai.com/v1
  prm_model: gpt-5.2
  prm_api_key: ""
  lora_rank: 32
  batch_size: 4
  resume_from_ckpt: ""      # ruta de checkpoint opcional para reanudar entrenamiento
  evolver_api_base: ""      # dejar vacío para reutilizar llm.api_base
  evolver_api_key: ""
  evolver_model: gpt-5.2

opd:
  enabled: false            # poner a true para activar OPD (destilación profesor)
  teacher_url: ""           # URL base del modelo profesor (OpenAI-compatible /v1/completions)
  teacher_model: ""         # nombre del modelo profesor (p. ej. Qwen/Qwen3-32B)
  teacher_api_key: ""       # clave API del modelo profesor
  kl_penalty_coef: 1.0      # coeficiente de penalización KL para OPD

max_context_tokens: 20000   # límite de tokens del prompt antes de truncar; 0 = sin truncar
                            # (recomendado en skills_only con modelos cloud de gran contexto)
context_window: 0           # ventana de contexto anunciada al agente (p. ej. umbral de compactación de OpenClaw);
                            # 0 = auto (≈200 000 en skills_only, 32 768 en rl/auto)

scheduler:                  # v0.3: planificador de meta-aprendizaje (auto-habilitado en modo auto)
  enabled: false            # modo auto lo habilita automáticamente; configurar manualmente para RL
  sleep_start: "23:00"
  sleep_end: "07:00"
  idle_threshold_minutes: 30
  min_window_minutes: 15
  calendar:
    enabled: false
    credentials_path: ""
    token_path: ""
```

</details>

---

## 💪 Modo Skills

**`metaclaw start --mode skills_only`**

El modo más ligero. Sin GPU, sin backend RL. MetaClaw envuelve tu LLM detrás de un proxy que inyecta skills relevantes en cada turno y resume automáticamente nuevos skills tras cada conversación.

Para proveedores personalizados compatibles con OpenAI, define `llm.api_base` con la URL base completa del chat (normalmente terminada en `/v1`, por ejemplo `https://your-gateway.example/v1`). En modo `skills_only`, MetaClaw reutiliza el mismo endpoint para comprimir el prompt y las llamadas auxiliares al LLM, salvo que configures un endpoint evolver aparte.

Los skills son instrucciones cortas en Markdown almacenadas en `~/.metaclaw/skills/` como archivos `SKILL.md` individuales. La biblioteca crece automáticamente con el uso.

Para precargar el banco de skills integrado (40+ skills para coding, seguridad, tareas agénticas, etc.):

```bash
cp -r memory_data/skills/* ~/.metaclaw/skills/
```

---

## 🔬 Modo RL

**`metaclaw start --mode rl`**

Todo lo del Modo Skills, más fine-tuning RL continuo a partir de conversaciones en vivo. Cada turno de conversación se tokeniza y se envía como muestra de entrenamiento. Un LLM juez (PRM) puntúa las respuestas de forma asíncrona, y un backend compatible con Tinker (Tinker Cloud, MinT o Weaver) ejecuta fine-tuning LoRA con hot-swap de pesos.

**Tinker**:

```bash
metaclaw config rl.backend tinker
metaclaw config rl.api_key sk-...
metaclaw config rl.model moonshotai/Kimi-K2.5
metaclaw config rl.prm_url https://api.openai.com/v1
metaclaw config rl.prm_api_key sk-...
metaclaw start --mode rl
```

**MinT**:

```bash
metaclaw config rl.backend mint
metaclaw config rl.api_key sk-mint-...
metaclaw config rl.base_url https://mint.macaron.xin/
metaclaw config rl.model Qwen/Qwen3-4B-Instruct-2507
metaclaw config rl.prm_url https://api.openai.com/v1
metaclaw config rl.prm_api_key sk-...
metaclaw start --mode rl
```

**Weaver**:

```bash
metaclaw config rl.backend weaver
metaclaw config rl.api_key sk-...
metaclaw config rl.base_url https://weaver-console.nex-agi.cn
metaclaw config rl.model Qwen/Qwen3-8B
metaclaw config rl.prm_url https://api.openai.com/v1
metaclaw config rl.prm_api_key sk-...
metaclaw start --mode rl
```

Un LLM evolucionador dedicado también extrae nuevos skills de los episodios fallidos, alimentándolos de vuelta a la biblioteca de skills.

**Rollout programático** (sin TUI de OpenClaw): establece `openclaw_env_data_dir` en un directorio de archivos JSONL de tareas:

```json
{"task_id": "task_1", "instruction": "Register the webhook at https://example.com/hook"}
```

### On-Policy Distillation (OPD)

OPD es un complemento opcional para el Modo RL. Destila un modelo profesor más grande en el estudiante on-policy: el estudiante genera respuestas normalmente, y el profesor proporciona log-probabilidades por token en esas mismas respuestas. Una penalización KL guía al estudiante hacia la distribución del profesor.

```bash
metaclaw config opd.enabled true
metaclaw config opd.teacher_url http://localhost:8082/v1
metaclaw config opd.teacher_model Qwen/Qwen3-32B
metaclaw config opd.kl_penalty_coef 1.0
```

El profesor debe servirse detrás de un endpoint `/v1/completions` compatible con OpenAI (p. ej. vLLM, SGLang). OPD puede combinarse con scoring PRM, ambos se ejecutan de forma asíncrona. Consulta `examples/run_conversation_opd.py` y `scripts/run_openclaw_tinker_opd.sh`.

---

## 🧠 Modo Auto (Por defecto)

**`metaclaw start`**

Todo lo del Modo RL, más un planificador de meta-aprendizaje que posterga las actualizaciones de pesos a ventanas de inactividad del usuario para que el agente nunca se interrumpa durante el uso activo. Este es el modo por defecto.

El paso de hot-swap de pesos RL pausa el agente durante varios minutos. En lugar de entrenar inmediatamente cuando un batch está lleno (como hace el Modo RL), el modo auto espera una ventana apropiada.

Tres condiciones activan una ventana de actualización (cualquiera es suficiente):

- **Horas de sueño**: horario de inicio/fin configurable (p. ej. 23:00 a 07:00)
- **Inactividad del teclado**: se activa tras N minutos de inactividad
- **Eventos de Google Calendar**: detecta reuniones para que las actualizaciones se ejecuten mientras estás fuera

```bash
metaclaw config scheduler.sleep_start "23:00"
metaclaw config scheduler.sleep_end   "07:00"
metaclaw config scheduler.idle_threshold_minutes 30

# Opcional: integración con Google Calendar
pip install -e ".[scheduler]"
metaclaw config scheduler.calendar.enabled true
metaclaw config scheduler.calendar.credentials_path ~/.metaclaw/client_secrets.json
```

Si el usuario regresa durante una actualización, el batch parcial se guarda y se retoma en la siguiente ventana.

Cada `ConversationSample` se etiqueta con una versión `skill_generation`. Cuando la evolución de skills incrementa la generación, el buffer RL se vacía para que solo las muestras post-evolución se usen en las actualizaciones de gradiente (separación de conjuntos support/query MAML).

---

## 🗑️ Desinstalacion

```bash
metaclaw uninstall
```

Elimina todo en un solo paso: detiene la instancia en ejecucion, limpia las referencias de MetaClaw en `~/.openclaw/openclaw.json`, elimina `~/.openclaw/extensions/metaclaw-openclaw/`, elimina `~/.metaclaw/`, desinstala el paquete pip y reinicia la pasarela OpenClaw. Se solicita confirmacion antes de eliminar.

Despues de desinstalar, elimine manualmente el repositorio si lo clono:

```bash
rm -rf /path/to/MetaClaw
```

---

## 📚 Cita

```bibtex
@misc{xia2026metaclaw,
  author       = {Xia, Peng and Chen, Jianwen and Yang, Xinyu and Tu, Haoqin and Han, Siwei and Qiu, Shi and Zheng, Zeyu and Xie, Cihang and Yao, Huaxiu},
  title        = {MetaClaw: Just Talk --- An Agent That Meta-Learns and Evolves in the Wild},
  year         = {2026},
  organization = {GitHub},
  url          = {https://github.com/aiming-lab/MetaClaw},
}
```

---

## 🙏 Agradecimientos

MetaClaw se construye sobre los siguientes proyectos de código abierto:

- [OpenClaw](https://openclaw.ai) - el framework central de agentes.
- [SkillRL](https://github.com/aiming-lab/SkillRL) - nuestro framework RL aumentado con skills.
- [Tinker](https://www.thinkingmachines.ai/tinker/) - usado para entrenamiento RL en línea.
- [MinT](https://github.com/MindLab-Research/mindlab-toolkit) - backend alternativo para entrenamiento RL en línea.
- [Weaver](https://github.com/nex-agi/weaver) - backend alternativo para entrenamiento RL en línea.
- [OpenClaw-RL](https://github.com/Gen-Verse/OpenClaw-RL) - inspiración para nuestro diseño RL.
- [awesome-openclaw-skills](https://github.com/VoltAgent/awesome-openclaw-skills) - proporciona la base de nuestro banco de skills.
- [NanoClaw](https://github.com/qwibitai/nanoclaw) - agente Claude personal de qwibitai, conectado a través del endpoint compatible con Anthropic `/v1/messages`.
- [NemoClaw](https://github.com/NVIDIA/NemoClaw) - plugin agente OpenShell de NVIDIA para inferencia.

---

## 📄 Licencia

Este proyecto está licenciado bajo la [Licencia MIT](LICENSE).
