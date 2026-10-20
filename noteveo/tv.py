"""Poner y quitar la prueba en la tele por ADB (research.md R7)."""

import json
import shlex
import subprocess
from pathlib import Path

FOLDER = "/sdcard/Movies/noteveo"
ASIDE = "/sdcard/Download/.noteveo-aparte"
CLIP_NAME = "noteveo-pared.mp4"
SCRIPT = "/data/local/tmp/noteveo-retirar.sh"
SCAN = "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{}"
DREAM = "am start -n com.android.systemui/.Somnambulator"


class TvError(RuntimeError):
    """La tele no responde o la orden falló."""


def _adb(device: str, *args: str, check: bool = True) -> str:
    result = subprocess.run(["adb", "-s", device, *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise TvError(f"adb {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def shell(device: str, command: str) -> str:
    return _adb(device, "shell", command)


def connect(device: str) -> None:
    subprocess.run(["adb", "connect", device], capture_output=True, text=True)
    state = subprocess.run(["adb", "-s", device, "get-state"], capture_output=True, text=True)
    if state.stdout.strip() != "device":
        raise TvError(
            f"la tele {device} no responde por ADB ({state.stderr.strip() or state.stdout.strip()})"
        )


def list_folder(device: str) -> list[str]:
    out = shell(device, f"ls -1 {FOLDER} 2>/dev/null")
    return [line.strip() for line in out.splitlines() if line.strip()]


def restore_script(previous: list[str]) -> str:
    """Script que quita el clip, devuelve lo apartado y avisa a MediaStore."""
    lines = [
        f"rm -f {FOLDER}/{CLIP_NAME}",
        SCAN.format(f"{FOLDER}/{CLIP_NAME}"),
    ]
    for name in previous:
        quoted = shlex.quote(name)
        lines += [
            f"mv {ASIDE}/{quoted} {FOLDER}/{quoted}",
            SCAN.format(shlex.quote(f"{FOLDER}/{name}")),
        ]
    lines.append(f"rm -f {SCRIPT}")
    return "\n".join(lines) + "\n"


def push(device: str, clip: Path, minutes: int, start: bool, state_file: Path) -> list[str]:
    """Deja el clip como único vídeo de la carpeta y programa su retirada."""
    connect(device)
    if shell(device, f"[ -f {SCRIPT} ] && echo si || echo no").strip() == "si":
        _stop_timer(device, state_file)
        shell(device, f"sh {SCRIPT}")  # una prueba anterior sigue puesta: se deshace primero
    previous = [name for name in list_folder(device) if name != CLIP_NAME]
    shell(device, f"mkdir -p {FOLDER} {ASIDE} && touch {ASIDE}/.nomedia")
    for name in previous:
        quoted = shlex.quote(name)
        shell(device, f"mv {FOLDER}/{quoted} {ASIDE}/{quoted}")
        shell(device, SCAN.format(shlex.quote(f"{FOLDER}/{name}")))
    _adb(device, "push", str(clip), f"{FOLDER}/{CLIP_NAME}")
    shell(device, SCAN.format(f"{FOLDER}/{CLIP_NAME}"))

    script = state_file.with_suffix(".sh")
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(restore_script(previous))
    _adb(device, "push", str(script), SCRIPT)
    pid = shell(
        device,
        f"nohup sh -c 'sleep {minutes * 60}; sh {SCRIPT}' > /dev/null 2>&1 & echo $!",
    ).strip()
    state = {"device": device, "previous": previous, "timer_pid": pid, "minutes": minutes}
    state_file.write_text(json.dumps(state, indent=2) + "\n")
    if start:
        shell(device, DREAM)
    return previous


def remove(device: str, state_file: Path) -> None:
    """Ejecuta ya el script de retirada que dejó push."""
    connect(device)
    exists = shell(device, f"[ -f {SCRIPT} ] && echo si || echo no").strip()
    if exists != "si":
        raise TvError("no hay prueba que quitar: el script de retirada ya no está en la tele")
    _stop_timer(device, state_file)
    shell(device, f"sh {SCRIPT}")


def _stop_timer(device: str, state_file: Path) -> None:
    """Para la retirada programada por un push anterior, si se conoce su proceso."""
    if not state_file.exists():
        return
    pid = json.loads(state_file.read_text()).get("timer_pid", "")
    if pid.isdigit():
        _adb(device, "shell", f"kill {pid}", check=False)


def timer_alive(device: str, state_file: Path) -> bool:
    """¿Sigue vivo en la tele el proceso de retirada automática?"""
    pid = json.loads(state_file.read_text()).get("timer_pid", "")
    return pid.isdigit() and shell(device, f"kill -0 {pid} 2>/dev/null && echo si").strip() == "si"
