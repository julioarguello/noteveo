# Plan de implementación: Imagen fija de la pared

**Rama**: `docs/001-imagen-fija` | **Fecha**: 2026-10-20 | **Spec**: [spec.md](spec.md)

**Entrada**: especificación de `specs/001-imagen-fija/spec.md`

## Resumen

Una herramienta de línea de órdenes en Python genera desde la foto de referencia un clip 4K de un
fotograma: la pared blanca que tapa la tele, con el degradado de luz interpolado desde la pared de
alrededor y el color neutro de la pintura (NCS S 0300-N). La copia a la tele por ADB, con retirada
automática. Con una foto de calibración desde el sofá mide ΔE2000 en los tres lados que tocan pared
y corrige los parámetros, hasta que cuadra. Decisiones y fuentes en [research.md](research.md).

## Contexto técnico

**Lenguaje/versión**: Python 3.12 (`.venv/`)

**Dependencias principales**: numpy, opencv-python-headless, colour-science, rawpy; `ffmpeg`
(libx265) y `adb` como programas externos

**Almacenamiento**: ficheros. Parámetros y medidas en texto dentro del repositorio; fotos, imágenes y
clips en `entrada/` y `salida/`, fuera de git

**Pruebas**: pytest, con escenas sintéticas generadas por los propios tests; ruff

**Plataforma**: macOS (genera y mide); Sony KD-65A8 con Android TV 10 y Aerial Views 1.8.5 (muestra)

**Tipo de proyecto**: herramienta de línea de órdenes (un paquete Python)

**Objetivos de rendimiento**: una vuelta de calibración (medir, corregir, generar, copiar) en menos de
2 minutos en el Mac, para que lo lento sea hacer la foto y no esperar al script

**Restricciones**: el fotograma sale idéntico byte a byte con las mismas entradas (SC-003); ningún borde de alto
contraste en la imagen (constitución III); nada de la casa en git (constitución V)

**Escala**: una tele, una pared, una persona que calibra

## Comprobación de la constitución

*Puerta: antes de la investigación y otra vez después del diseño.*

| Principio | Cómo lo cumple el plan | Estado |
|---|---|---|
| I. Idioma | Código y órdenes en inglés; mensajes del programa, specs y docs en castellano | Cumple |
| II. De menos a más | El reproductor está probado (2026-10-20); 001 es el primer contenido y es una imagen fija, lo más simple | Cumple |
| III. La OLED manda | Bordes: diferencia entre píxeles vecinos ≤ 1 nivel de 10 bits, comprobada por un test (SC-005). Quietud: es una imagen de prueba que se retira sola (R7). Brillo: el script informa del APL (R6) | Parcial: el APL no tiene umbral hasta la primera medida; la retirada automática está por medir |
| IV. Todo sale de un script | Esquinas, máscaras, degradado y curvas en `config/wall.toml`; ninguna edición de imagen a mano | Cumple |
| V. La casa no se publica | `entrada/` y `salida/` ignorados; tests sintéticos; un test falla si git sigue una imagen o un vídeo | Cumple |
| VI. Se mide en la tele | Cada vuelta de calibración guarda fecha, hora y ajustes de la tele; los ajustes se apuntan en `docs/medidas-tele.md` | Cumple |

Después del diseño: sin cambios. La desviación de III se explica en «Seguimiento de complejidad».

## Estructura del proyecto

### Documentación (esta spec)

```text
specs/001-imagen-fija/
├── plan.md              # este fichero
├── research.md          # fase 0
├── data-model.md        # fase 1
├── quickstart.md        # fase 1
├── contracts/cli.md     # fase 1: las órdenes de la herramienta
└── tasks.md             # fase 2 (/speckit-tasks)
```

### Código (raíz del repositorio)

```text
pyproject.toml           # dependencias, ruff y pytest
Makefile                 # make ci = ruff + pytest
config/
└── wall.toml            # parámetros (texto, en git)
calibracion/
└── medidas.csv          # una fila por foto de calibración: fecha, ΔE por lado, ajustes (en git)
noteveo/
├── __main__.py          # python -m noteveo <orden>
├── params.py            # leer y escribir config/wall.toml
├── color.py             # sRGB ↔ lineal ↔ Lab y ΔE2000
├── geometry.py          # esquinas de la pantalla, homografía, máscaras
├── wall.py              # superficie de luz y render de la pared en luz lineal
├── encode.py            # fotograma a clip HEVC 10 bits con ffmpeg
├── measure.py           # franjas dentro/fuera, ΔE2000, rechazo de fotos
├── correct.py           # cociente por canal a corrección de parámetros
└── tv.py                # adb: poner, quitar, retirada automática
tests/
├── synthetic.py         # escenas sintéticas (nunca fotos de la casa)
├── test_color.py
├── test_geometry.py
├── test_wall.py
├── test_measure.py
├── test_correct.py
├── test_determinism.py  # SC-003: el fotograma, no el clip
├── test_edges.py        # SC-005
└── test_privacy.py      # git no sigue imágenes ni vídeos
```

**Decisión de estructura**: un solo paquete, `noteveo/`, junto a `scripts/` (que son los scripts
comunes copiados de `.agent`, no código del proyecto). `config/` y `calibracion/` contienen solo
números, así que van en git; las imágenes no.

## Seguimiento de complejidad

| Desviación | Por qué | Alternativa descartada |
|---|---|---|
| III.4: el APL no tiene umbral | Sin una medida en la tele no se sabe a partir de qué nivel actúa el ABL; un número inventado sería peor que ninguno | Fijar un umbral de una ficha técnica: no es una medida (principio VI) |
