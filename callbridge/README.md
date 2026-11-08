# CallBridge — revisión de llamadas en el PC

Aplicación de escritorio (Windows/Linux/macOS) para **transcribir, diarizar y resumir** llamadas
grabadas, y **revisarlas** con una línea de tiempo donde cada hablante es una pista.
Todo se procesa en local: el audio no sale del PC.

> Forma parte del proyecto "móvil como altavoz-micrófono para Teams". Esta es la parte del PC
> (revisión). El puente de audio móvil ↔ PC es la siguiente fase (ver *Hoja de ruta*).

## Qué hace

1. **Importas** una grabación (WAV, MP3, M4A, OGG/Opus, FLAC…).
2. **Transcribe** con Whisper (`large-v3-turbo` por defecto), que funciona en español, inglés y con los dos mezclados.
3. **Diariza**: separa a los hablantes en **N1, N2, N3…** sin huellas de voz previas ni datos de nadie.
   - En una grabación **estéreo del puente**, el canal izquierdo es tu micro y queda como **«Yo»**
     sin margen de error. Solo el canal derecho (lo que llega de Teams) se separa en N1, N2…
   - Una grabación **mono** se separa entera.
4. **Revisas** en la interfaz:
   - Una pista por hablante con bloques de color, más la forma de onda de cada canal.
   - **Arrastra un bloque** a otra pista para cambiarlo de hablante, o **arrastra sus bordes** para ajustar el corte.
   - **Renombra** a N1 → «Marta»: se aplica a la transcripción y al resumen. También puedes **fusionar** dos
     hablantes que son la misma persona o **añadir** una pista nueva.
   - Botón ▶ en cada hablante para escuchar una muestra de su voz.
   - **Dividir** un bloque en el cursor, **unir** con el siguiente, editar el texto y deshacer/rehacer.
   - Escucha **solo tu canal** o **solo el remoto**, a 0,75×–2×.
   - Transcripción sincronizada con la reproducción, editable y con búsqueda.
   - Las frases de «Yo» que parecen **eco** del remoto se marcan con rayas para revisarlas.
5. **Resumen**, con dos opciones:
   - **Con Claude (recomendado):** *Exportar → Copiar para Claude* y pégalo en un chat con la skill
     [`acta-llamada`](claude-skill/acta-llamada/SKILL.md). Te devuelve el acta y propone quién puede ser cada N# según
     las pistas del texto. No hace falta descargar ningún modelo GGUF. Solo se envía el texto revisado, nunca el audio.
   - **En local:** con cualquier modelo **GGUF** que elijas (Qwen, Llama, Gemma, Mistral…). Si la llamada es larga, la resume por bloques.
     Útil si la llamada no puede salir del PC.
6. **Exporta** a Markdown (resumen + transcripción), TXT o SRT, o lo **copia** al portapapeles para pegarlo en Teams, correo, etc.

### Instalar la skill en Claude

1. Comprime la carpeta `claude-skill/acta-llamada` en un ZIP (clic derecho → *Comprimir*). La carpeta debe quedar en la raíz del ZIP.
2. En claude.ai: *Configuración → Capacidades → Skills → Subir skill* y elige el ZIP.
3. En un chat, pega el texto de *Copiar para Claude* (o adjunta el archivo `_para_claude.md`) y pide «haz el acta».

> Revisa la política de tu empresa antes de subir el contenido de reuniones de trabajo a un servicio externo.

Todo se guarda solo: cada llamada es una carpeta con `audio.*`, `project.json` y `exportado/`.

## Instalación

### Opción A: el .exe ya compilado

Cada cambio en `callbridge/` dispara el workflow **«CallBridge – exe de Windows»** de GitHub Actions.
Descarga el artefacto `CallBridge-windows`, descomprímelo y ejecuta `CallBridge.exe`.

### Opción B: desde el código (Python 3.10–3.12)

```bat
cd callbridge
build_exe.bat           :: crea .venv, instala todo y genera dist\CallBridge\CallBridge.exe
```

O sin empaquetar:

```bash
cd callbridge
python -m venv .venv && .venv\Scripts\activate      # (Linux/mac: source .venv/bin/activate)
pip install -r requirements.txt
pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu   # opcional, para resúmenes
python -m callbridge                 # ventana de escritorio
python -m callbridge --browser       # o en el navegador
```

### Modelos (se descargan solos la primera vez, salvo el GGUF)

| Uso | Modelo por defecto | Tamaño | Dónde |
|---|---|---|---|
| Transcripción | Whisper `large-v3-turbo` int8 (faster-whisper) | ~0,8 GB | Hugging Face, automático |
| Segmentación de voz | pyannote segmentation 3.0 (ONNX) | ~6 MB | GitHub de sherpa-onnx, automático |
| Huella de voz para agrupar | NeMo TitaNet small (ONNX) | ~40 MB | GitHub de sherpa-onnx, automático |
| Resumen local (opcional) | **El que elijas** (.gguf). Recomendado: `Qwen2.5-7B-Instruct-Q4_K_M.gguf` | ~4,7 GB | Lo descargas tú y lo seleccionas en *Ajustes* |

Con un i5 de 12.ª generación, una llamada de 1 hora tarda aproximadamente entre 20 y 40 minutos en total.
Si tu equipo va justo, prueba los modelos Whisper `small` o `medium` en *Ajustes*, aunque son peores con los idiomas mezclados.

## Privacidad: todo en local

- **La transcripción, la diarización y el resumen con GGUF se hacen en tu PC.** El audio y el texto nunca salen de él.
- La interfaz es una web local que solo escucha en `127.0.0.1` (no es accesible desde la red), y la telemetría de las librerías está desactivada.
- La única conexión posible es **descargar los modelos públicos la primera vez** (Whisper desde Hugging Face y los de diarización desde GitHub).
  Una vez descargados se cargan siempre desde disco.
- **Modo «Solo local»** (*Ajustes → Privacidad*, desmarcar «Permitir descargar modelos»): la app no se conecta a nada.
  Si tu PC del trabajo no puede descargar, prepara los modelos en otro equipo y cópialos:

  ```bash
  python preparar_modelos.py --out modelos          # ~0,9 GB con large-v3-turbo
  ```

  Copia la carpeta `modelos` al portátil e indícala en *Ajustes → Carpeta de modelos*.
- Lo único que puedes enviar fuera, y solo si quieres, es el texto de *Copiar para Claude*.

**¿Por qué no WhisperX?** WhisperX usa el mismo motor de transcripción (faster-whisper) y, para diarizar, pyannote con PyTorch.
Aquí se usa ese mismo modelo de segmentación de pyannote 3.0, pero en ONNX con sherpa-onnx: es local, igual de capaz,
mucho más ligero (sin PyTorch, que ocupa ~2 GB) y no exige token de Hugging Face. WhisperX añade además un alineado por idioma
(wav2vec2) que funciona peor cuando se mezclan español e inglés.

## Atajos

| Tecla | Acción |
|---|---|
| Espacio | Reproducir / pausa |
| ← / → | −5 s / +5 s |
| ↑ / ↓ | Segmento anterior / siguiente |
| 1…9 | Asignar el segmento al hablante n.º |
| S | Dividir en el cursor |
| M | Unir con el siguiente |
| Supr | Eliminar segmento |
| Ctrl+Z / Ctrl+Shift+Z | Deshacer / rehacer |
| Ctrl + rueda | Zoom |
| Doble clic en un bloque | Reproducirlo |

## Ajustes útiles

- **Umbral de agrupación** (0,85 por defecto): si salen demasiados hablantes, súbelo; si junta a dos personas, bájalo.
  También puedes indicar el número exacto de hablantes al procesar.
- **Contexto inicial**: pon nombres propios, de proyectos o siglas para que Whisper los escriba bien.
- **Instrucciones del resumen**: cambia el formato (acta, tareas, correo de seguimiento…).

## Arquitectura

```
callbridge/
  callbridge/
    pipeline.py    decodifica (PyAV) → Whisper por canal → diarización (sherpa-onnx) → combina
    align.py       asigna hablante a cada palabra y corta segmentos en los cambios (funciones puras)
    summarize.py   resumen map-reduce con llama.cpp sobre cualquier GGUF
    project.py     formato del proyecto y exportaciones (MD/TXT/SRT)
    server.py      API local (Flask, solo 127.0.0.1) + cola de trabajos en segundo plano
    __main__.py    ventana de escritorio (pywebview / WebView2) o navegador
    web/           interfaz (HTML/CSS/JS sin dependencias)
  tests/           pruebas (pytest); test_e2e usa diarización real
```

Pruebas:

```bash
pip install pytest
pytest -q tests
# Prueba completa con diarización real (descarga ~45 MB de GitHub):
curl -LO https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/0-four-speakers-zh.wav
CALLBRIDGE_TEST_WAV=0-four-speakers-zh.wav pytest -q tests/test_e2e.py
```

## Licencias de terceros

Todas las dependencias permiten publicar el código y usarlo sin fines comerciales (y también con ellos):

| Componente | Licencia |
|---|---|
| faster-whisper, CTranslate2 | MIT |
| Pesos de Whisper (OpenAI) | MIT |
| sherpa-onnx | Apache 2.0 |
| pyannote segmentation 3.0 (pesos) | MIT |
| NeMo TitaNet (pesos) | CC-BY-4.0 |
| llama.cpp / llama-cpp-python | MIT |
| PyAV / FFmpeg | BSD / LGPL (enlazado dinámico) |
| Flask | BSD-3 |
| pywebview | BSD-3 |

Los modelos GGUF tienen su propia licencia (Qwen2.5: Apache 2.0; Llama: Llama Community License; Gemma: Gemma Terms).

## Hoja de ruta

- [x] Revisión en el PC: transcripción, diarización, pistas por hablante, etiquetado, resumen y exportación.
- [ ] **Puente de audio**: APK (micro y altavoz del móvil por USB/ADB, botón de cascos o manos libres) + servicio en el PC
      con VB-CABLE, que graba directamente en estéreo (Yo | Remoto) y abre la llamada aquí al colgar.
- [ ] Modo «casi en directo»: transcribir mientras dura la llamada (opcional).
- [ ] Aceleración por GPU integrada (OpenVINO/Vulkan) si compensa.

> ⚖️ Grabar una llamada en la que participas es legal en España para uso propio, pero en el trabajo
> conviene avisar y respetar la política de tu empresa.
