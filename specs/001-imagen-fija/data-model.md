# Modelo de datos: Imagen fija de la pared

Lo que se guarda y dónde. Lo que va en git son números; las imágenes nunca (constitución V).

## Parámetros — `config/wall.toml` (en git)

| Campo | Qué es | Validación |
|---|---|---|
| `reference.photo` | Nombre del fichero de la foto de referencia en `entrada/` | Existe; no es una ruta absoluta |
| `screen.corners` | Cuatro esquinas de la pantalla en la foto, en píxeles, en orden: arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda | Cuadrilátero convexo dentro de la foto |
| `masks.<nombre>` | Polígonos que no son pared (mueble colgado, columna, mueble de madera, jarrón) | Cada uno con tres puntos o más |
| `ring.width` | Ancho del anillo de pared alrededor del marco, en % del ancho de la pantalla | Mayor que 0 |
| `light.smoothing` | Suavizado de cada perfil de borde, en % del ancho de la pantalla | Mayor que 0, hasta 20 |
| `color.level` | Nivel lineal medio de la pared en la tele | Mayor que 0, hasta 1; 0,25 al empezar |
| `color.gain` | Ganancia lineal por canal (R, G, B) y su variación de lado a lado | Positivas |
| `output.seconds` | Duración del clip | Entero ≥ 1 |
| `tv.device` | `ip:puerto` de la tele para ADB | Contiene `:` |
| `oled.apl_max` | APL máximo admitido | Vacío hasta la primera medida en la tele (FR-010) |

Cada corrección (orden `correct`) reescribe `color.gain` y deja el cambio a la vista en el diff.

## Imagen de pared — `salida/` (fuera de git)

- `salida/wall.png`: fotograma de 3840×2160 en 16 bits, para mirarlo en el Mac.
- `salida/wall.mp4`: el clip que va a la tele (HEVC 10 bits, BT.709).
- Se acompañan de su huella SHA-256, que se imprime al generarlos. Solo la de `wall.png` tiene que
  repetirse (SC-003).

## Foto de calibración — `entrada/` (fuera de git)

- DNG o JPEG desde el sofá, con la tele mostrando `wall.mp4`.
- Estados: **aceptada** (marco localizado y franjas sin saturar) o **rechazada**, con el motivo
  (FR-008).

## Medida de calibración — `calibracion/medidas.csv` (en git)

Una fila por foto aceptada:

| Columna | Qué es |
|---|---|
| `taken_at` | Fecha y hora de la foto (EXIF), con zona horaria |
| `photo` | Nombre del fichero en `entrada/` |
| `params_sha` | Huella de `config/wall.toml` con el que se generó lo que se fotografió |
| `de_top`, `de_left`, `de_right` | ΔE2000 entre dentro y fuera, por lado |
| `ratio_top`, `ratio_left`, `ratio_right` | Cociente fuera/dentro en luz lineal, R/G/B: lo que usa `correct` |
| `exposure`, `iso` | Exposición de la foto (EXIF), para rechazar un cambio no avisado |
| `apl` | Nivel medio de la imagen, en % del blanco máximo |
| `tv_settings` | Modo de imagen, temperatura de color, sensor de luz, tal como estaban |
| `reflections` | Si había reflejos sobre el marco (lo anota quien hace la foto) |

## Transiciones

```text
foto de referencia ──locate──▶ parámetros ──render──▶ imagen de pared ──push──▶ en la tele
                                    ▲                                              │
                                    └──correct── medida ◀──measure── foto de calibración
```

La prueba termina cuando una medida da ΔE2000 ≤ 3 en los tres lados (SC-001) y Julio lo confirma
desde el sofá (SC-002). Después, `remove` quita la imagen de la tele.
