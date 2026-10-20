"""Constitución V: git no sigue ninguna imagen ni ningún vídeo."""

import subprocess

from noteveo import ROOT

MEDIA = {".jpg", ".jpeg", ".png", ".heic", ".dng", ".webp", ".gif", ".tif", ".tiff",
         ".mp4", ".mov", ".mkv", ".webm"}  # fmt: skip


def media_files(paths: list[str]) -> list[str]:
    return [p for p in paths if any(p.lower().endswith(ext) for ext in MEDIA)]


def test_control_detects_an_image():
    assert media_files(["README.md", "salida/a.PNG", "x/clip.mp4"]) == [
        "salida/a.PNG",
        "x/clip.mp4",
    ]


def test_git_tracks_no_media():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert len(tracked) > 20, "git ls-files devolvió casi nada: el test no estaría mirando"
    assert media_files(tracked) == []
