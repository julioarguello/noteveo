# Contrato: órdenes de `python -m noteveo`

Cada orden escribe para la persona en castellano, por la salida estándar; los errores van por la
salida de error. Códigos de salida: `0` hecho, `1` error de uso o de entrada, `2` foto rechazada o
dispositivo no disponible. Ninguna orden escribe imágenes fuera de `salida/`.

## `locate`

Propone las esquinas de la pantalla en la foto de referencia y las escribe en `config/wall.toml`.

- Entrada: `--photo entrada/<fichero>`.
- Salida: las cuatro esquinas y una vista previa con el contorno en `salida/locate.png`.
- Falla con `1` si no encuentra un cuadrilátero oscuro que ocupe al menos el 5 % de la foto.

## `render`

Genera `salida/wall.png` y `salida/wall.mp4` desde `config/wall.toml`.

- Imprime la huella SHA-256 de los dos ficheros y el APL de la imagen.
- Misma entrada y mismos parámetros dan la misma huella (SC-003).

## `push`

Copia `salida/wall.mp4` a la tele y la deja mostrándolo.

- Opciones: `--device <ip:puerto>` (por defecto, el de `docs/medidas-tele.md`), `--minutes N`
  (retirada automática, por defecto 30), `--start` (arranca el salvapantallas ya).
- Guarda la lista de lo que había en la carpeta de la tele para que `remove` lo restaure.
- Falla con `2` si la tele no responde.

## `remove`

Quita el clip de la tele y deja la carpeta como estaba antes de `push`.

## `measure`

Mide una foto de calibración.

- Entrada: `--photo entrada/<fichero>`, `--tv-settings "<texto>"`, `--reflections yes|no`.
- Salida: ΔE2000 por lado (arriba, izquierda, derecha), APL y la fila añadida a
  `calibracion/medidas.csv`.
- Falla con `2`, sin añadir fila, si la foto no sirve: marco no localizado, franjas saturadas o
  exposición distinta a la anterior sin decirlo con `--new-exposure`.

## `correct`

Convierte la última medida en una corrección de `color.gain`.

- Sin `--apply`, muestra el cambio y no escribe (FR-007: Julio lo ve antes de aplicarlo).
- Con `--apply`, reescribe `config/wall.toml`.
