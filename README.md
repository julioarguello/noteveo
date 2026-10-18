# noTeVeo

Que la tele del salón desaparezca: la pantalla muestra la pared que tiene detrás, como si no hubiera tele, con el tono lo más parecido posible al de la pared real y con movimiento suave para no quemar la OLED.

La tele es una Sony **KD-65A8** (OLED 65", 2020, Android TV). «BRAVIA 4K UR3», lo que sale en Ajustes → Información, es el nombre de la plataforma, no el modelo.

No hay nada hecho para Android TV que haga esto (búsqueda del 2026-10-17). Samsung lo inventó con el «modo ambiente» de sus teles y lo está retirando.

## Estrategia

De menos a más trabajo; no se pasa a un nivel sin haber probado el anterior.

1. **Reproductor: [Aerial Views](https://github.com/theothernt/AerialViews).** Salvapantallas libre que reproduce vídeos y fotos propios desde USB, Samba o WebDAV. En la A8 (Android TV 10, no Google TV) se instala desde Google Play y se elige en Ajustes → Salvapantallas, sin ADB: comprobado el 2026-10-18. Las medidas de la tele están en [docs/medidas-tele.md](docs/medidas-tele.md).

2. **Contenido: un vídeo en bucle de la pared.** Es el trabajo de verdad (ver abajo).
3. **App propia** (un `DreamService` de Android) solo si hace falta adaptar la imagen en vivo a la luz de la habitación. No antes de probar 1 y 2.

## Cómo se hace el contenido

1. **Foto de la pared** desde el sofá, con la luz de la tarde y la tele apagada, encuadrando la pared alrededor de la tele.
2. **Rectificar**: corregir la perspectiva, recortar a 16:9 la zona que tapa la tele y rellenar lo tapado (las texturas de pared se generan bien).
3. **Calibrar**: mostrar la imagen en la tele, fotografiar tele y pared desde el sofá con el móvil en exposición y balance de blancos manuales, comparar los píxeles justo dentro y justo fuera del marco, y ajustar curvas. Se repite hasta que cuadra.
4. **Movimiento**: deriva lenta de la imagen entera (unos píxeles), variación suave de la luz y algún elemento vivo (una planta que se mece, quizá un gato de vez en cuando). Bucle sin corte visible.

Todo con scripts reproducibles (Python), no a mano.

## Lo que ya sabemos

- **OLED.** Una pared clara a pantalla completa hace que la tele baje el brillo global (ABL), y las OLED atenúan la imagen estática: por eso vídeo y no foto. Lo que más marca la pantalla es un borde fijo de alto contraste (un cuadro, una balda), no el gato. Apagarla de noche protege más que cualquier animación.
- **Física.** La tele emite luz y la pared la refleja: solo coinciden en una franja de luz ambiente. Se calibra para la luz real de uso (tarde, indirecta) y se acepta que a mediodía no cuadre. El efecto solo funciona desde un punto de vista.
- **Sensor de luz.** La A8 tiene sensor de luz ambiente y Sony lo usa para el brillo («Sensor de luz ambiente / Auto luminancia»); dejarlo activado ya resuelve el brillo. Android lo ofrece a cualquier app sin permiso, así que una app propia podría leer los lux; qué valores da está por medir. Es un sensor de brillo, no de color: el tono tendría que salir de la hora del día u otra pista.

## Carpetas

| Carpeta | Contenido |
|---|---|
| `entrada/` | Fotos originales de la pared y de calibración. **No se publican**: fuera de git. |
| `salida/` | Imágenes y vídeos generados. Fuera de git: también muestran la casa. |
| `docs/` | Medidas de la tele y notas. |
| `scripts/` | Automatismos. |
| `specs/` | Una especificación por entregable (metodología [GitHub Spec Kit](https://github.com/github/spec-kit)). |
