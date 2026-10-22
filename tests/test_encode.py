"""El clip dura toda la prueba: Aerial Views funde a negro cada vez que repite un vídeo."""

import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from noteveo import encode

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="sin ffmpeg ni ffprobe no se puede codificar",
)


def test_clip_seconds_rounds_up_to_whole_segments():
    assert encode.clip_seconds(10) == 10
    assert encode.clip_seconds(11) == 20
    assert encode.clip_seconds(1800) == 1800
    assert encode.clip_seconds(1, segment=10) == 10


def _duration(clip) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(clip)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


@needs_ffmpeg
@pytest.mark.parametrize("seconds", [1, 5])
def test_clip_lasts_the_requested_time(tmp_path, seconds):
    png = tmp_path / "frame.png"
    cv2.imwrite(str(png), np.full((36, 64, 3), 40000, dtype=np.uint16))
    clip = tmp_path / "wall.mp4"

    total = encode.encode_clip(png, clip, seconds, segment=1)

    assert total == seconds
    assert _duration(clip) == pytest.approx(seconds, abs=0.1)
    assert not (tmp_path / "wall-tramo.mp4").exists()
