<!--
Informe de impacto — 1.0.0 → 2.0.0 (2026-10-21)
- Redefinido (MAYOR), V: «La casa no se publica» pasa a «Qué se publica de la casa». Julio decidió el
  2026-10-21 publicar las fotos del salón como casos reales de los tests, reducidas y sin
  metadatos; la ubicación sigue sin publicarse nunca.
- Pendiente: ninguno.
-->
<!--
Informe de impacto — plantilla → 1.0.0 (2026-10-20)
- Primera versión. Principios sacados del README y de lo medido en la tele (docs/medidas-tele.md).
- Plantillas de Spec Kit (.specify/templates/) sin cambios: siguen en inglés; lo que se rellena a
  partir de ellas se escribe en castellano.
- Pendiente: ninguno.
-->

# Constitución del repositorio noteveo

Este documento fija cómo se trabaja en noteveo: qué se hace antes de qué, qué no se publica nunca y
qué tiene que cumplir todo lo que se muestre en la tele. El objetivo del proyecto está en el README.

## Principios

### I. El idioma lo decide quién lo lee

1. Lo que lee una persona se escribe en castellano claro: el README, `docs/`, las specs, los
   mensajes de commit y de pull request, y lo que los scripts escriben para quien los usa.
2. Los identificadores del código (funciones, variables, parámetros) van en inglés.
3. Las plantillas de Spec Kit se quedan en inglés, tal como llegan; lo que se escribe a partir de
   ellas va en castellano.

### II. De menos a más trabajo

1. El proyecto avanza por niveles: **reproductor** (Aerial Views), **contenido** (la imagen y el
   vídeo de la pared) y, solo si hace falta, **app propia** (un `DreamService`).
2. No se empieza un nivel sin haber probado el anterior en la tele. La app propia necesita una
   razón medida: algo que el contenido no consiga sin ella.
3. Dentro de un nivel, lo más simple primero: una imagen fija se prueba antes que un vídeo.

### III. La OLED manda (NO NEGOCIABLE)

Lo que se deja puesto horas en una OLED la marca. Todo contenido pensado para quedarse en pantalla
cumple:

1. **Sin bordes fijos de alto contraste.** Una línea nítida que no se mueve (el canto de una balda,
   un marco) es lo que más marca. Si el diseño la necesita, se suaviza o se mueve.
2. **Nada quieto.** Lo que se deja puesto es vídeo, no foto: como mínimo, una deriva lenta de la
   imagen entera. Una imagen fija solo se usa para probar y se quita después.
3. **Brillo contenido.** Una imagen clara a pantalla completa hace que la tele baje el brillo
   global (ABL) y desgasta el panel. Se busca el tono justo para pasar por pared, no más.
4. Cada spec de contenido dice cómo se comprueban estos tres puntos con un script, con umbrales
   medibles.

### IV. Todo sale de un script

1. Cada imagen o vídeo de `salida/` se genera con un script de Python a partir de `entrada/`. Nada
   se retoca a mano: si hace falta un ajuste, es un parámetro del script.
2. Los parámetros (recortes, curvas de color, velocidades) viven en el repositorio, en texto, para
   que el resultado se pueda repetir.
3. Las dependencias se declaran en el repositorio y se instalan en `.venv/`.

### V. Qué se publica de la casa (NO NEGOCIABLE)

El repositorio es público y lo que se publica queda en el historial. Qué se ve de la casa lo decide
Julio.

1. Las fotos entran en git solo como casos reales de los tests, en `tests/fixtures/salon/`: copias
   reducidas y sin ningún metadato. Los originales (`entrada/`) y lo generado (`salida/`) siguen
   fuera de git.
2. Nunca se publica la ubicación: ningún fichero lleva GPS ni datos que localicen la casa.
   `tests/test_privacy.py` falla si una foto publicada tiene metadatos o si hay una imagen o un
   vídeo fuera de `tests/fixtures/salon/`.
3. Antes de cada push se pasan el escáner de secretos y `make ci`.

### VI. Se mide en la tele y se apunta con fecha

1. Lo que se afirma sobre la tele o sobre la luz del salón se comprueba en la tele real y se apunta
   con la fecha y con cómo repetir la medida (`docs/medidas-tele.md`).
2. Lo que se lee en un comercio, un foro o una ficha técnica es una pista, no una medida: no se
   apunta como hecho hasta comprobarlo.
3. Un contenido no está terminado hasta verlo en la tele desde el sofá.

## Cómo se publica

- Nada se commitea directamente en `main`. Cada cambio va en una rama `<tipo>/<NNN>-<resumen>`,
  donde `NNN` es el número de la spec, y entra por pull request.
- Julio revisa y aprueba cada pull request.

## Entregables

| Spec | Qué |
|---|---|
| 001 | Imagen fija de la pared compuesta y calibrada, probada en la tele. |
| 002 | Vídeo en bucle a partir de 001: deriva, luz que cambia y una planta con su sombra. |
| 003 | App propia, solo si 002 demuestra que hace falta (principio II). |

## Gobierno

- Esta constitución rige cómo se trabaja en este repositorio y prevalece sobre las specs.
- Los cambios se proponen por pull request y los decide Julio.
- Versiones: MAYOR si se quita o redefine un principio; MENOR si se añade uno o se amplía de forma
  material; PARCHE si solo se aclara la redacción.

**Versión**: 2.0.0 | **Ratificada**: 2026-10-20 | **Última modificación**: 2026-10-21
