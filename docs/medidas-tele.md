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
- Antes estaba **Sony Living Decor** (`com.sony.dtv.livingfit`, v2.37.15), el salvapantallas decorativo de Sony. No sabemos si deja poner fotos propias: no se ha mirado.
- Salta a los 5 minutos sin uso (`screen_off_timeout` = 300000). La tele se apaga a las 4 h (`sleep_timeout`).

## Sensor de luz

- **Está expuesto a las apps**: `android.sensor.light` (MediaTek, por cambio, sin permiso). Una app propia podría leer los lux.
- No se ha podido leer un valor: `adb` no tiene orden para eso, y el sistema no registra lux (`dumpsys display`) ni había nadie escuchando el sensor. El brillo automático de Sony no pasa por el servicio de sensores de Android.
- Sigue siendo un sensor de brillo, no de color.

## Cómo repetir las medidas

```sh
adb connect 192.168.1.49:5555
adb shell getprop ro.build.version.release
adb shell dumpsys sensorservice | sed -n '/Sensor List/,/^$/p'
adb shell cmd package query-services -a android.service.dreams.DreamService | grep name=
adb shell settings get secure screensaver_components
```

En el Mac, el daemon de `adb` tiene que arrancar fuera del sandbox de Claude Code: dentro, `adb connect` falla con «No route to host» aunque el puerto 5555 responda.
