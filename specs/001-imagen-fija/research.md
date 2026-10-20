# Investigación: Imagen fija de la pared

Cada decisión dice qué se eligió, por qué y qué se descartó. Lo que se midió lleva fecha y contra qué.

## R1. La imagen llega a la tele como clip de vídeo, no como foto

- **Decisión**: la «imagen fija» se entrega como un clip HEVC 10 bits, 3840×2160, de un fotograma
  repetido durante 10 s, que Aerial Views repite en bucle.
- **Por qué**: medido el 2026-10-20 en el código de Aerial Views (`ui/core/ImagePlayerView.kt`,
  rama `main`): las fotos se decodifican al tamaño de la vista (`resolveTargetSize()` usa el ancho y
  alto de la vista o de `displayMetrics`). En la A8 la interfaz va a 1920×1080 (`docs/medidas-tele.md`),
  así que una foto se vería a 1080p, en 8 bits y reescalada por la tele. Además, los rótulos de las
  fotos están activados por defecto (`overlayMetadata1Photos` = descripción, lugar y fecha, en
  `models/prefs/GeneralPrefs.kt`). El vídeo se decodifica a 4K, y el camino ya está comprobado con
  `noteveo-prueba.mp4` (2026-10-20).
- **Ventaja añadida**: la 002 (vídeo) usa el mismo camino; lo que se aprenda calibrando vale tal cual.
- **Descartado**: foto PNG o JPEG (1080p, 8 bits, rótulos); clip H.264 8 bits (bandas en un
  degradado de blanco casi uniforme).

## R2. El color de partida es el de la pintura; el tinte lo pone la calibración

- **Decisión**: la pared se genera como un gris neutro (NCS S 0300-N es un neutro: 0 % de
  cromaticidad), con la claridad de partida L\* ≈ 96. La calibración ajusta el tinte y el nivel.
- **Por qué**: la pintura es neutra y mate (spec, Aclaraciones), así que el color que el ojo ve en la
  pared es el de la luz que le llega. Las fotos de `entrada/` tienen el balance de blancos automático
  del móvil (Pixel 7a), así que su tinte no es fiable; la foto de calibración, con tele y pared en la
  misma toma, sí lo es, porque compara las dos bajo la misma cámara.
- **Fuente de L\***: 95,9 según [plan-home.com](https://plan-home.com/compare-colors/s-0300-n/s-2002-y20r),
  que lo deriva de valores RGB de fabricantes y no de una medida; consultado el 2026-10-20. Solo sirve
  de punto de partida: la primera vuelta de calibración lo corrige.
- **Descartado**: sacar el color medio de la pared de las fotos de `entrada/` (balance de blancos
  automático, exposición desconocida).

## R3. Geometría: la pantalla tapa la pared que está justo detrás

- **Decisión**: en la foto de referencia (`PXL_20261020_130130671.jpg`, frontal desde el sofá) se
  localizan las cuatro esquinas de la zona visible de la pantalla. Una homografía lleva esa zona a
  3840×2160. La pared de alrededor se lleva al mismo sistema de coordenadas, ampliado más allá del
  marco.
- **Paralaje despreciado en 001**: la tele está unos centímetros por delante de la pared y el sofá a
  unos metros, así que la pared que tapa se desplaza respecto a la pantalla en pocos píxeles. Se
  revisa si la calibración deja un escalón de luz que lo delate.
- **Esquinas como parámetros**: el script propone las esquinas (la pantalla apagada es el
  cuadrilátero oscuro más grande) y las escribe en el fichero de parámetros. Si la detección falla, se
  corrigen allí, en texto (constitución IV: es un parámetro, no un retoque de la imagen).

## R4. La luz dentro del marco se interpola desde la pared de alrededor

- **Decisión**: se toma un anillo de pared alrededor del marco, en luz lineal. Se excluyen con
  polígonos en los parámetros el mueble colgado, la columna, el mueble de madera y el jarrón. Sobre
  ese anillo se ajusta una superficie suave (polinomio de grado bajo en x e y), que da cómo varía el
  brillo dentro de la pantalla. El color sale de R2.
- **Por qué**: la pared es lisa. Lo único que hay que inventar es el degradado de luz, y una
  superficie suave no puede crear bordes (constitución III).
- **Lado derecho**: la columna está pegada a la tele y su cara frontal es otra superficie, con otra
  luz. Si el anillo de la derecha solo ve columna, ese lado se ajusta aparte. Se decide con la primera
  foto de calibración.
- **Descartado**: rellenar la zona con un modelo generativo (no es reproducible bit a bit, y para una
  pared lisa no aporta).

## R5. Calibración por cociente en luz lineal, en tres lados

- **Decisión**: en la foto de calibración se miden dos franjas por lado (dentro de la pantalla, junto
  al canto negro, y fuera, en la pared) en arriba, izquierda y derecha. Abajo está el mueble. La
  corrección es el cociente fuera/dentro por canal en luz lineal, extendido a toda la imagen como un
  plano (ganancia que varía suavemente de lado a lado). Se itera hasta que ΔE2000 ≤ 3 en los tres
  lados.
- **ΔE2000** se calcula con `colour-science`, sobre Lab obtenido de la foto suponiendo primarios
  sRGB. La foto solo sirve para comparar dentro con fuera; el valor absoluto no importa.
- **Foto de calibración**: en DNG. El Pixel 7a de Julio tiene la opción «RAW + JPEG» en Cámara →
  Ajustes → Avanzado (comprobado por Julio el 2026-10-20). El DNG es lineal y no lleva el tono del
  procesado del móvil. El JPEG que sale al lado solo sirve para mirarlo. El script rechaza fotos con zonas quemadas en las franjas.
- **Localizar el marco en la foto de calibración**: el canto negro de la tele es la línea oscura entre
  dos zonas claras. Si eso falla, el clip lleva un primer segundo con cuatro marcas en las esquinas y
  se hace una foto en ese segundo.
- **Descartado**: comparar los cuatro lados (abajo no hay pared); ajustar a ojo (constitución IV).

## R6. La tele: lo que la calibración tiene que mantener fijo

- El brillo automático de Sony y el modo de imagen cambian lo que sale de la pantalla. Se calibra con
  los ajustes del día a día y se apuntan en `docs/medidas-tele.md` con la primera foto de calibración:
  modo de imagen, temperatura de color, sensor de luz.
- **ABL**: el script informa del nivel medio de la imagen (APL, en % del blanco máximo). Una pared
  casi blanca a pantalla completa puede bajar el brillo global. Si pasa, se nota porque la
  calibración no converge al subir el nivel.

## R7. Poner y quitar la prueba en la tele

- **Poner**: `adb push` del clip a `/sdcard/Movies/noteveo/`, aviso a MediaStore
  (`MEDIA_SCANNER_SCAN_FILE`, como con el clip de prueba) y, opcional, arrancar el salvapantallas.
- **Arrancar el salvapantallas**: la actividad `com.android.systemui/.Somnambulator` existe en la tele
  (`cmd package resolve-activity`, medido el 2026-10-20). No se ha ejecutado todavía.
  `cmd dreams` no existe en Android 10.
- **Quitar**: borrar el clip de la carpeta y devolver la que había antes. El script guarda la lista
  de ficheros que encontró al poner la prueba.
- **Retirada automática** (constitución III): al poner la prueba, el script deja en la tele un
  `sleep` seguido de un borrado, lanzado con `nohup`, para que la imagen fija se quite sola aunque nadie se
  acuerde. Que sobreviva a cerrar la conexión ADB está por medir; si no sobrevive, el script lo dice y
  pide quitarla a mano.

## R8. Entorno

- **Python 3.12** en `.venv/` (medido el 2026-10-20: 3.12.15). Dependencias en `pyproject.toml`:
  `numpy`, `opencv-python-headless` (homografía, contornos), `colour-science` (ΔE2000, espacios de
  color), `rawpy` (DNG), `pytest`, `ruff`.
- **Fuera de Python**: `ffmpeg` con `libx265` (el clip de prueba se generó con él el 2026-10-18) y
  `adb`. En el Mac, el daemon de `adb` arranca fuera del sandbox de Claude Code (`docs/medidas-tele.md`).
- **Pruebas sin fotos de la casa**: los tests generan sus propias escenas sintéticas (un rectángulo
  oscuro sobre un degradado) y nunca leen `entrada/` (constitución V).
