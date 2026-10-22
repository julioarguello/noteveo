# Medidas de la tele

Sony KD-65A8 del salón, medida por ADB por red el 2026-10-18.

## Sistema

| Qué | Valor |
|---|---|
| Plataforma (`ro.product.model`) | BRAVIA 4K UR3 (año de modelo 2020) |
| Android | **10** (API 29). No 9 como decía un comercio. |
| Parche de seguridad | 2026-02-01 |
| Compilación | `Sony/BRAVIA_UR3_EU/BRAVIA_UR3:10/QTG3.200305.006.S97/662301` |
| Panel | 3840×2160 |
| Interfaz de Android | 1920×1080 a 60 Hz (el vídeo sí se decodifica a 4K) |
| HDR | HDR10, HLG y Dolby Vision |
| Almacenamiento interno libre | 2,3 GB |

## Salvapantallas

- **Aerial Views se elige desde el menú**, sin ADB: Ajustes → Salvapantallas. Comprobado: después de elegirla, `screensaver_components` vale `com.neilturner.aerialviews/com.neilturner.aerialviews.ui.screensaver.DreamActivity`.
- Versión instalada: 1.8.5 desde Google Play. **Esa versión pide API 29 como mínimo, justo la de la tele**: si una versión futura sube el mínimo, Play dejará de actualizarla. La 1.8.5 sigue funcionando; conviene guardar su APK.
- **Reproduce vídeos propios desde el almacenamiento interno**: un clip copiado por ADB a
  `/sdcard/Movies/noteveo/` (Android lo indexa en MediaStore) se ve en bucle con la fuente «Vídeos
  locales» activada y las demás apagadas. Comprobado por Julio el 2026-10-20.
- **La retirada automática sobrevive a cerrar ADB**: `push --minutes 3` a las 22:17 del
  2026-10-20, `adb disconnect` enseguida; a las 22:20 la carpeta había vuelto sola a como estaba (el
  clip de la pared fuera, el de prueba de vuelta, el script de retirada borrado y ningún `sleep`
  vivo). El proceso lanzado con `nohup` desde `adb shell` sigue corriendo sin conexión.
- **Arrancar el salvapantallas desde el Mac**: `com.android.systemui/.Somnambulator` existe en la
  tele (2026-10-20), pero no se ha lanzado todavía.
- **`Somnambulator` arranca Aerial Views**: `push --start` a las 07:35 del 2026-10-22. El
  salvapantallas tarda unos segundos: justo después de la orden, `dumpsys dreams` daba
  `mCurrentDream: null`; poco después, `mWakefulness=Dreaming` y
  `mCurrentDreamName=…aerialviews…DreamActivity` como actividad en primer plano.
- **Parar la retirada automática exige matar el `sleep`**: el `sh` de la tele atrapa SIGTERM y lo
  aplaza hasta que acaba la orden en primer plano. Medido el 2026-10-22 con dos temporizadores de
  15 s: con `kill` a secas el `sh` seguía vivo y murió al acabar el `sleep` **sin ejecutar** lo que
  venía detrás; con `pkill -P <pid>; kill <pid>` murió en el acto. Un temporizador viejo no quita,
  por tanto, un clip nuevo.
- Antes estaba **Sony Living Decor** (`com.sony.dtv.livingfit`, v2.37.15), el salvapantallas decorativo de Sony. No sabemos si deja poner fotos propias: no se ha mirado.
- Salta a los 5 minutos sin uso (`screen_off_timeout` = 300000). La tele se apaga a las 4 h (`sleep_timeout`).

## Sensor de luz

- **Está expuesto a las apps**: `android.sensor.light` (MediaTek, por cambio, sin permiso). Una app propia podría leer los lux.
- No se ha podido leer un valor: `adb` no tiene orden para eso, y el sistema no registra lux (`dumpsys display`) ni había nadie escuchando el sensor. El brillo automático de Sony no pasa por el servicio de sensores de Android.
- Sigue siendo un sensor de brillo, no de color.

## Ajustes de imagen con los que se calibra

Leídos del menú Imagen de la entrada «Apps» (la que usa Aerial Views) el 2026-10-22, de fotos de
Julio. Son los del día a día; la calibración se hace con ellos y no se tocan entre vueltas
(research.md R6).

| Grupo | Ajuste | Valor |
|---|---|---|
| Básico | Modo de imagen | Standard |
| | Modo de imagen automático | Off |
| | Sensor de luz | On |
| Brillo | Brillo | Max |
| | Contraste | 90 |
| | Gamma | 0 |
| | Nivel de negro | 50 |
| | Ajuste de negro | Medium |
| | Realce avanzado del contraste | Medium |
| | Luminancia máxima | Medium |
| Color | Color | 60 |
| | Matiz | 0 |
| | Temperatura de color | Neutral |
| | Live Colour | Medium |
| Claridad | Nitidez | 60 |
| | Reducción de ruido aleatorio | Auto |
| | Reducción de ruido digital | Auto |
| | Gradación suave | Low |
| Movimiento | Modo cine | Auto |
| Señal de vídeo | Modo HDR, rango de vídeo HDMI, espacio de color | Auto |

No se leen en las fotos los valores de Reality Creation ni de Motionflow.

Tres de estos ajustes cambian la imagen según lo que haya en pantalla o en la sala, y son los
candidatos si la calibración no converge: el **realce avanzado del contraste** (ajusta el contraste
según el contenido), el **sensor de luz** (cambia el brillo con la luz de la sala) y **Live Colour**
(satura los colores; en una pared casi neutra debería afectar poco).

## Cómo repetir las medidas

```sh
adb connect 192.168.1.49:5555
adb shell getprop ro.build.version.release
adb shell dumpsys sensorservice | sed -n '/Sensor List/,/^$/p'
adb shell cmd package query-services -a android.service.dreams.DreamService | grep name=
adb shell settings get secure screensaver_components
```

En el Mac, el daemon de `adb` tiene que arrancar fuera del sandbox de Claude Code: dentro, `adb connect` falla con «No route to host» aunque el puerto 5555 responda.

Cualquier orden `adb` lanzada dentro del sandbox, aunque sea `adb devices`, arranca allí el daemon,
y desde entonces `adb connect` falla también fuera. Se arregla con `adb kill-server` y conectando de
nuevo fuera del sandbox (2026-10-22).
