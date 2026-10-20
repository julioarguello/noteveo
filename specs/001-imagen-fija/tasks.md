# Tareas: Imagen fija de la pared

**Entrada**: `specs/001-imagen-fija/` — [plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[quickstart.md](quickstart.md)

**Pruebas**: sí. La spec las pide (SC-003, SC-005) y la constitución V exige un test de privacidad.
Todas usan escenas sintéticas de `tests/synthetic.py`; ninguna lee `entrada/`.

**Formato**: `[ID] [P?] [Historia] Descripción`. `[P]` = puede ir en paralelo (otro fichero, sin
dependencias pendientes).

## Fase 1: Preparación

- [ ] T001 Crear `pyproject.toml` con el paquete `noteveo`, Python ≥ 3.12 y las dependencias de research.md R8 (`numpy`, `opencv-python-headless`, `colour-science`, `rawpy`; de desarrollo `pytest`, `ruff`), e instalarlas en `.venv/`
- [ ] T002 [P] Crear `Makefile` con `make ci` = `ruff check` + `ruff format --check` + `pytest`
- [ ] T003 [P] Crear el paquete vacío `noteveo/__init__.py` y `noteveo/__main__.py` con `argparse` y las seis órdenes de contracts/cli.md (`locate`, `render`, `push`, `remove`, `measure`, `correct`) sin implementar; los códigos de salida son `0` hecho, `1` error de uso o de entrada, `2` foto rechazada o dispositivo no disponible
- [ ] T004 [P] Test de privacidad en `tests/test_privacy.py`: falla si `git ls-files` devuelve algún fichero con extensión de imagen o vídeo (`jpg`, `jpeg`, `png`, `heic`, `dng`, `webp`, `gif`, `mp4`, `mov`, `mkv`); control positivo: la misma función marca una lista sintética que contiene `a.png`

## Fase 2: Base (bloquea todas las historias)

- [ ] T005 Parámetros en `noteveo/params.py`: leer y escribir `config/wall.toml` con los campos de data-model.md y sus validaciones (`screen.corners` «cuadrilátero convexo dentro de la foto»; `masks.<nombre>` «cada uno con tres puntos o más»; `ring.width` «mayor que 0»; `light.degree` «1 a 3»; `color.base_lightness` «0 a 100; 95,9 al empezar»; `color.gain` «positivas»; `output.seconds` «≥ 1»; `oled.apl_max` «vacío hasta la primera medida»). Un valor inválido sale con un mensaje que nombra el campo y lo admitido
- [ ] T006 [P] Escenas sintéticas en `tests/synthetic.py`: una «habitación» con un degradado suave, un cuadrilátero oscuro (la tele apagada) y, para calibración, el mismo cuadrilátero claro con un canto negro y un desfase de color conocido entre dentro y fuera
- [ ] T007 [P] Conversión de color en `noteveo/color.py`: sRGB ↔ lineal, lineal → Lab (primarios sRGB, D65) y ΔE2000 con `colour-science`; test en `tests/test_color.py` con un par de colores de ΔE conocido
- [ ] T008 Crear `config/wall.toml` inicial con `reference.photo = "PXL_20261020_130130671.jpg"`, `color.base_lightness = 95.9`, `light.degree = 2`, `color.gain = [1, 1, 1]` y `output.seconds = 10`

## Fase 3: Historia 1 — Ver la pared en la tele desde el sofá (P1) — MVP

**Objetivo**: la tele muestra la pared generada a pantalla completa, sin bandas ni rótulos.

**Prueba independiente**: `quickstart.md` pasos 2 y 3.

### Pruebas de la Historia 1

- [ ] T009 [P] [US1] `tests/test_geometry.py`: en una escena sintética, `locate` encuentra las cuatro esquinas a menos de 3 px; y falla con `1` si el cuadrilátero oscuro ocupa menos del 5 % de la foto
- [ ] T010 [P] [US1] `tests/test_edges.py` (SC-005): en el fotograma generado, antes del tramado, ningún par de píxeles vecinos difiere en más de un nivel de 10 bits; mutación de control: una imagen con un escalón de 2 niveles hace fallar la comprobación
- [ ] T011 [P] [US1] `tests/test_determinism.py` (SC-003): dos `render` con los mismos parámetros dan el mismo `wall.png` byte a byte

### Implementación de la Historia 1

- [ ] T012 [US1] `noteveo/geometry.py`: proponer las esquinas de la pantalla (mayor cuadrilátero oscuro convexo), homografía foto ↔ 3840×2160 ampliada al anillo de pared, y máscaras de polígonos (research.md R3)
- [ ] T013 [US1] Orden `locate` en `noteveo/__main__.py`: escribe `screen.corners` en `config/wall.toml` y la vista previa `salida/locate.png`
- [ ] T014 [US1] `noteveo/wall.py`: anillo de pared en luz lineal sin las máscaras, ajuste de la superficie de grado `light.degree`, fotograma 3840×2160 neutro con `color.base_lightness` y `color.gain` (research.md R2, R4)
- [ ] T015 [US1] `noteveo/encode.py`: fotograma → `salida/wall.png` (16 bits) y `salida/wall.mp4` (HEVC 10 bits, BT.709, `-tag:v hvc1`, `output.seconds`) con `ffmpeg`, tramado antes de cuantizar a 10 bits
- [ ] T016 [US1] Orden `render`: imprime SHA-256 de los dos ficheros, el APL (% del blanco máximo) y el mayor salto entre vecinos; sale con `1` si el salto supera un nivel de 10 bits
- [ ] T017 [US1] `noteveo/tv.py` y órdenes `push`/`remove`: `adb push` a `/sdcard/Movies/noteveo/`, aviso a MediaStore, `--start` con `am start -n com.android.systemui/.Somnambulator`, retirada automática con `nohup sh -c 'sleep N; rm …'`, lista de lo que había guardada en `salida/tv-before.json` para `remove`; sale con `2` si la tele no responde
- [ ] T018 [US1] Medir en la tele si la retirada automática sobrevive a cerrar ADB y si `Somnambulator` arranca Aerial Views; apuntar el resultado con fecha en `docs/medidas-tele.md` y ajustar `push` si falla (research.md R7)
- [ ] T019 [US1] Primera imagen real: `locate` + `render` con la foto de referencia, revisar `salida/locate.png`, ajustar máscaras en `config/wall.toml`, `push --start` y verlo en la tele

**Punto de control**: la pared se ve en la tele. Todavía sin calibrar.

## Fase 4: Historia 2 — Calibrar el tono con una foto (P1)

**Objetivo**: con una foto DNG desde el sofá, medir ΔE2000 por lado y corregir hasta ΔE ≤ 3.

**Prueba independiente**: `quickstart.md` paso 4.

### Pruebas de la Historia 2

- [ ] T020 [P] [US2] `tests/test_measure.py`: en una escena de calibración sintética con un desfase conocido, `measure` da el ΔE esperado (±0,5) en arriba, izquierda y derecha; con las franjas saturadas, sale con `2` y no añade fila
- [ ] T021 [P] [US2] `tests/test_correct.py`: aplicar la corrección al desfase sintético deja ΔE ≤ 1 en los tres lados; sin `--apply` no se escribe `config/wall.toml`

### Implementación de la Historia 2

- [ ] T022 [US2] `noteveo/measure.py`: leer DNG con `rawpy` (lineal) o JPEG, localizar el canto negro de la tele, franjas dentro y fuera en los tres lados que tocan pared, ΔE2000, rechazo con motivo (marco no localizado, franjas saturadas, exposición distinta sin `--new-exposure`) (research.md R5)
- [ ] T023 [US2] Orden `measure`: imprime ΔE por lado y APL, y añade la fila a `calibracion/medidas.csv` con las columnas de data-model.md (`taken_at`, `photo`, `params_sha`, `de_top`, `de_left`, `de_right`, `apl`, `tv_settings`, `reflections`)
- [ ] T024 [US2] `noteveo/correct.py` y orden `correct`: cociente fuera/dentro por canal en luz lineal → nuevo `color.gain` con variación de lado a lado; muestra el cambio y solo escribe con `--apply`
- [ ] T025 [US2] Apuntar en `docs/medidas-tele.md` los ajustes de imagen de la tele con los que se calibra (modo de imagen, temperatura de color, sensor de luz) (research.md R6)
- [ ] T026 [US2] Vueltas de calibración con Julio, por la tarde, hasta ΔE2000 ≤ 3 en los tres lados (SC-001) y su confirmación desde el sofá (SC-002); fijar `oled.apl_max` con la medida (FR-010)

**Punto de control**: SC-001 y SC-002 cumplidos; `remove` deja la tele como estaba.

## Fase 5: Cierre

- [ ] T027 [P] Actualizar el README: estado del nivel 2 y cómo se usa la herramienta (enlace a quickstart.md)
- [ ] T028 Pasar `make ci` y gitleaks, y recorrer `quickstart.md` de punta a punta

## Dependencias

- Fase 1 → Fase 2 → Historia 1 → Historia 2. La Historia 2 necesita una imagen en la tele para
  fotografiarla, así que no puede ir en paralelo con la Historia 1.
- Dentro de cada historia, los tests marcados `[P]` se escriben a la vez y antes de la
  implementación.
- T018 y T019 necesitan la tele; T026 necesita a Julio en el sofá por la tarde.

## Paralelo

```text
Fase 1:     T002, T003 y T004 a la vez, después de T001
Fase 2:     T006 y T007 a la vez con T005
Historia 1: T009, T010 y T011 a la vez
Historia 2: T020 y T021 a la vez
```

## Estrategia

1. **MVP = Historia 1**: la pared sin calibrar en la tele. Dice si la geometría y el camino del clip
   funcionan antes de invertir en calibrar.
2. **Historia 2**: calibrar. Es donde está el riesgo de verdad (si el tono se puede igualar).
3. Con la 001 cerrada, la 002 (vídeo, planta) parte de los mismos parámetros.
