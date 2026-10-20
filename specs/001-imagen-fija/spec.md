# Especificación: Imagen fija de la pared

**Rama**: `docs/001-imagen-fija`

**Creada**: 2026-10-20

**Estado**: Borrador

**Entrada**: «A partir de las fotos de `entrada/`, generar con un script una imagen 3840×2160 que,
mostrada en la tele, haga parecer que la tele no está: la pared blanca de detrás, con la perspectiva
del sofá, y algo que aporte (plantas, o una balda falsa que disimule el marco). Calibrada para la luz
de tarde (indirecta, casa orientada casi al norte). Es una prueba: la imagen fija no se deja puesta;
el vídeo es la 002.»

## Contexto

La tele está en un hueco de pared blanca y lisa: encima, un mueble blanco colgado; a la derecha, una
columna blanca que llega casi al canto de la tele; debajo, el mueble de madera sobre el que apoya en
sus patas. Lo que la pantalla tiene que mostrar es la pared que tapa, que es lisa: el trabajo no está
en inventar textura, sino en que el tono y la luz cuadren con la pared que se ve alrededor del marco.

Julio no quiere solo pared: prefiere que la imagen aporte algo, como unas plantas o una balda que
convierta el marco de la tele en parte del mueble. Ese elemento choca con la constitución (principio
III): una balda es justo el borde fijo de alto contraste que más marca una OLED.

Esta spec es la primera prueba en la tele. Comprueba que se puede igualar el tono antes de invertir en
movimiento (spec 002).

## Aclaraciones

### Sesión 2026-10-20

- P: ¿Valen las fotos de `entrada/`, hechas con luz de día en una casa orientada casi al norte?
  → R: Sí para esta spec. Son del 2026-10-20 a las 15:01 (hora de Madrid, según el EXIF), no de la
  mañana. Sirven para la geometría y la composición. El tono no se saca de ellas, sino de las fotos de
  calibración (Historia 2), que se hacen con la imagen ya puesta en la tele.

## Escenarios de uso y pruebas *(obligatorio)*

### Historia 1 - Ver la pared en la tele desde el sofá (Prioridad: P1)

Julio pone la imagen en la tele, se sienta en su sitio del sofá y ve la pared donde estaba la tele:
el blanco de dentro del marco sigue al de fuera, y la luz cae igual que sobre la pared real.

**Por qué esta prioridad**: es el proyecto entero. Si el tono no cuadra en una imagen quieta, no
cuadrará en un vídeo.

**Prueba independiente**: con la imagen en la tele, una foto desde el sofá muestra los cuatro lados
del marco sin salto de tono entre dentro y fuera.

**Escenas de aceptación**:

1. **Dado** que la imagen está en la carpeta que lee el salvapantallas, **cuando** salta el
   salvapantallas, **entonces** la tele muestra la imagen a pantalla completa, sin bandas, sin
   recortes y sin rótulos.
2. **Dado** que Julio mira desde su sitio del sofá por la tarde, **cuando** recorre con la vista el
   marco, **entonces** la pared sigue a ambos lados sin un escalón de brillo ni de color.

---

### Historia 2 - Calibrar el tono con una foto (Prioridad: P1)

Julio fotografía la tele (con la imagen puesta) y la pared desde el sofá con el móvil en exposición y
balance de blancos fijos, y deja la foto en `entrada/`. El script mide la diferencia de color justo
dentro y justo fuera del marco en cada lado, propone la corrección y genera una imagen nueva. Se
repite hasta que cuadra.

**Por qué esta prioridad**: sin calibrar no se iguala el tono; la cámara del móvil y la tele no ven
el blanco igual. Es P1 con la Historia 1 porque la Historia 1 no se cumple sin esta.

**Prueba independiente**: con una foto de calibración, el script da la diferencia por lado. Con la
imagen corregida y una foto nueva, la diferencia baja.

**Escenas de aceptación**:

1. **Dada** una foto de calibración, **cuando** se pasa al script, **entonces** informa de la
   diferencia de color en cada uno de los cuatro lados del marco y de la corrección que aplica.
2. **Dada** una foto movida o con la exposición en automático (la pared quemada o el marco sin
   localizar), **cuando** se pasa al script, **entonces** la rechaza diciendo por qué, sin generar una
   corrección.

---

### Historia 3 - Algo que aporte (Prioridad: P2)

Sobre la pared aparece [NEEDS CLARIFICATION: qué elemento: plantas detrás de la tele, una balda que
convierta el canto inferior del marco en su borde, o nada en 001 y dejarlo para el vídeo].

**Por qué esta prioridad**: Julio lo pidió, pero solo tiene sentido sobre una pared que ya cuadra
(Historia 1).

**Prueba independiente**: el elemento se ve desde el sofá como parte de la habitación (apoyado en
algo, con su sombra hacia donde cae la luz) y no como una pegatina.

**Escenas de aceptación**:

1. **Dada** la imagen calibrada, **cuando** se añade el elemento, **entonces** la pared alrededor
   del elemento mantiene la calibración de la Historia 2.
2. **Dado** el elemento, **cuando** se analiza la imagen, **entonces** ningún borde suyo supera el
   contraste máximo que fija el plan (principio III de la constitución).

---

### Casos límite

- **Reflejos**: la pantalla es brillante y refleja la habitación (se ve en las fotos de `entrada/`).
  El contenido no los puede quitar: a la hora de calibrar se anota si había reflejos sobre el marco.
- **Brillo automático de la tele**: el sensor de luz ambiente de Sony cambia el brillo según la luz.
  Se calibra con ese ajuste como está en el día a día; si cambiarlo hiciera falta, se decide aparte.
- **Otra hora o la luz encendida**: a mediodía o de noche no cuadrará (README, «Física»). Se acepta;
  la spec solo exige la tarde.
- **Otro asiento**: desde otro sitio la perspectiva no casa. Se acepta.
- **El marco y las patas siguen ahí**: el canto negro de la tele y sus patas no desaparecen con
  ninguna imagen. Es la razón de la idea de la balda (Historia 3).
- **Imagen fija olvidada**: si la prueba se deja puesta, marca la pantalla. Ver FR-008.

## Requisitos *(obligatorio)*

### Generación

- **FR-001**: Un script genera la imagen a partir de las fotos de `entrada/` y de unos parámetros en
  texto guardados en el repositorio, sin ningún paso a mano (constitución IV).
- **FR-002**: La imagen tiene la resolución del panel, 3840×2160, y sale en `salida/`.
- **FR-003**: Lo que muestra es la pared que la tele tapa vista desde el sofá: el degradado de luz
  dentro del marco continúa el de la pared de alrededor en los cuatro lados.
- **FR-004**: Con las mismas entradas y parámetros, el script genera la misma imagen.

### Calibración

- **FR-005**: Un script mide, en una foto de calibración, la diferencia de color entre una franja
  justo dentro y otra justo fuera del marco, en cada lado, y la informa por lado.
- **FR-006**: El script convierte esa medida en una corrección de los parámetros de FR-001. Julio
  puede ver qué cambia antes de aplicarla.
- **FR-007**: Una foto de calibración que no sirve (marco no localizado, zonas quemadas, exposición
  distinta a la de la anterior sin decirlo) se rechaza con el motivo.

### OLED y entrega

- **FR-008**: La imagen fija solo está en la tele durante una prueba. Al terminar, el salvapantallas
  vuelve a lo que tenía antes. Ninguna imagen fija de esta spec queda como salvapantallas sin
  supervisión (constitución III).
- **FR-009**: El script informa del nivel medio de brillo de la imagen, para vigilar que la tele no
  baje el brillo global al mostrarla.
- **FR-010**: La imagen llega a la tele por ADB, a la carpeta que lee el salvapantallas (carpeta y modo
  en `docs/medidas-tele.md`).

### Privacidad

- **FR-011**: Ni las fotos, ni la imagen, ni recortes o miniaturas de ellas entran en git, issues o
  pull requests (constitución V). Lo que se informa del avance son números, no imágenes.

### Entidades clave

- **Foto de referencia**: foto de la pared desde el sofá con la tele apagada. Da la geometría: dónde
  está el marco y cómo cae la luz.
- **Parámetros**: texto en el repositorio con todo lo que decide la imagen: recorte, perspectiva,
  degradado, curvas de color y el elemento de la Historia 3.
- **Imagen de pared**: el resultado, 3840×2160, en `salida/`.
- **Foto de calibración**: tele con la imagen puesta y pared, desde el sofá, con exposición y
  balance de blancos fijos.
- **Medida de calibración**: la diferencia de color por lado del marco, con la fecha y la hora de
  la foto.

## Criterios de éxito *(obligatorio)*

### Resultados medibles

- **SC-001**: En una foto de calibración tomada por la tarde, la diferencia de color entre dentro y
  fuera del marco es como mucho la que el ojo apenas distingue (ΔE2000 ≤ 3) en cada uno de los
  cuatro lados.
- **SC-002**: Desde el sofá, por la tarde, Julio no ve dónde acaba la pantalla y empieza la pared en
  los lados donde la tele toca pared (sin contar el canto negro del marco).
- **SC-003**: Regenerar la imagen con las mismas entradas da un fichero idéntico.
- **SC-004**: Una vuelta de calibración (foto, medida, imagen nueva, copia a la tele) se hace sin
  editar nada a mano.

## Suposiciones

- **Fotos de `entrada/`**: cuatro, del 2026-10-20 a las 15:01 (hora de Madrid), hechas con un Pixel
  7a en automático. La foto frontal desde el sofá (`PXL_20261020_130130671.jpg`) es la de referencia;
  las otras tres ayudan con la geometría.
- **Punto de vista**: el sitio de Julio en el sofá, sentado. Las fotos de calibración se hacen desde
  ahí.
- **Luz objetivo**: la tarde, con la luz que entra por las ventanas y las lámparas apagadas.
- **Reproductor**: Aerial Views reproduce lo que hay en `/sdcard/Movies/noteveo/` (comprobado por
  Julio el 2026-10-20 con un clip de prueba). Si no muestra bien una imagen fija, se convierte en un
  clip quieto de pocos segundos; es un detalle del plan.
- **Fuera de alcance**: el movimiento, la sombra de planta y el bucle (spec 002), y cualquier app
  propia (spec 003).
