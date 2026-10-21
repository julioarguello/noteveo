# Fotos reales del salón

Las cuatro fotos de la pared que se usaron para la spec 001, hechas con un Pixel 7a el 2026-10-20
entre las 15:01 y las 15:02 (hora de Madrid), con la tele apagada.

Son copias reducidas a 1600 px de ancho y **sin ningún metadato**: los originales, en `entrada/`
(fuera de git), llevan la ubicación GPS. `tests/test_privacy.py` falla si una de estas copias
vuelve a tener EXIF. Julio decidió publicarlas el 2026-10-21 (constitución 2.0.0, principio V).

| Foto | Qué es | Esquinas de la pantalla (px, a 1600 de ancho) |
|---|---|---|
| `PXL_20261020_130130671.jpg` | Frontal desde el sofá; la de referencia | Las de `wall.toml` |
| `PXL_20261020_130152148.jpg` | Frontal, de cerca | (360, 342) (1218, 355) (1183, 819) (396, 813) |
| `PXL_20261020_130138633.jpg` | Oblicua desde la izquierda; reflejo de la ventana arriba a la izquierda | (608, 425) (1043, 397) (1036, 700) (610, 788) |
| `PXL_20261020_130201290.jpg` | Oblicua desde la derecha; cajón abierto y consola junto a la esquina de abajo a la derecha | (535, 457) (1033, 448) (1032, 853) (560, 790) |

Las esquinas de las frontales son las que da `locate`, revisadas a ojo sobre una cuadrícula; las de
las oblicuas están medidas a mano, porque `locate` falla en ellas (`tests/test_real_photos.py`).
`wall.toml` son los parámetros de `config/wall.toml` del 2026-10-20 escalados a este tamaño, con la
ganancia neutra.
