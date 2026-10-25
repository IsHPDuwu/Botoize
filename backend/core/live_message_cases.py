"""Synthetic, non-user media fixtures for explicitly requested live acceptance."""
import io
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import wave
import zlib


def synthetic_media():
    def chunk(kind, body):
        return struct.pack('!I', len(body)) + kind + body + struct.pack('!I', zlib.crc32(kind + body))
    width, height = 160, 80
    pixels = b''.join(b'\0' + bytes([79, 70, 229]) * width for _ in range(height))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b''.join(struct.pack('<h', int(1500 * math.sin(2 * math.pi * 440 * i / 16000)))
                                    for i in range(16000)))
    return {
        'image': (1, 'qq-proxy-test.png', png),
        'voice': (3, 'qq-proxy-test.wav', audio.getvalue()),
        'file': (4, 'qq-proxy-test.txt', b'QQ Bot Proxy synthetic acceptance fixture. No user data.\n'),
    }


def synthetic_video():
    # Optional live-test dependency, not required by the application runtime.
    import imageio_ffmpeg
    with tempfile.TemporaryDirectory(prefix='qq-proxy-media-') as directory:
        output = Path(directory) / 'qq-proxy-test.mp4'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'color=c=0x4F46E5:s=320x180:d=1:r=10',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)],
                       check=True, capture_output=True, timeout=30)
        return 2, 'qq-proxy-test.mp4', output.read_bytes()
