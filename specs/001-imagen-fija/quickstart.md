# Validación rápida: Imagen fija de la pared

Cómo comprobar de punta a punta que la 001 cumple la spec. Las órdenes están en
[contracts/cli.md](contracts/cli.md); los ficheros, en [data-model.md](data-model.md).

## Requisitos previos

- `.venv/` con las dependencias de `pyproject.toml`, más `ffmpeg` y `adb` en el `PATH`.
- La foto de referencia en `entrada/`.
- La tele encendida y en la red. En el Mac, el daemon de `adb` arrancado fuera del sandbox de
  Claude Code (`docs/medidas-tele.md`).

## 1. Las pruebas pasan sin fotos de la casa

```sh
make ci
```

Esperado: ruff limpio y pytest en verde. `test_privacy.py` falla si git sigue alguna imagen o vídeo.

## 2. La imagen se genera y es reproducible (SC-003)

```sh
.venv/bin/python -m noteveo locate --photo entrada/PXL_20261020_130130671.jpg
.venv/bin/python -m noteveo render
.venv/bin/python -m noteveo render
```

Esperado: las dos ejecuciones de `render` imprimen la misma huella de `wall.png` y un salto máximo
entre píxeles vecinos de un nivel o menos. `salida/locate.png` muestra el
contorno sobre la pantalla.

## 3. Se ve en la tele (Historia 1)

```sh
.venv/bin/python -m noteveo push --start --minutes 30
```

Esperado: la tele muestra la pared a pantalla completa, sin bandas ni rótulos. A los 30 minutos el
clip desaparece solo de `/sdcard/Movies/noteveo/`.

## 4. Una vuelta de calibración (Historia 2, SC-004)

Desde el sofá, por la tarde, con el móvil en RAW o con exposición y balance de blancos bloqueados,
foto de tele y pared. Se deja en `entrada/` y:

```sh
.venv/bin/python -m noteveo measure --photo entrada/<foto> --tv-settings "<modo, temperatura, sensor>" --reflections no
.venv/bin/python -m noteveo correct
.venv/bin/python -m noteveo correct --apply
.venv/bin/python -m noteveo render
.venv/bin/python -m noteveo push --start
```

Esperado: `measure` da ΔE por lado y añade una fila a `calibracion/medidas.csv`; nada se edita a mano.

## 5. Terminado (SC-001, SC-002)

Esperado: una fila de `calibracion/medidas.csv` con ΔE2000 ≤ 3 en arriba, izquierda y derecha, y
Julio que, desde el sofá, no ve dónde acaba la pantalla. Después:

```sh
.venv/bin/python -m noteveo remove
```
