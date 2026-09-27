import json
import subprocess
import tempfile
import unittest
import re
from pathlib import Path

from core.processor.pipeline import process_video_full
from core.processor.audio_mixer import mix_multiple_external_audios


class Step2RenderTests(unittest.TestCase):
    def test_frame_title_small_blur_regions_and_zero_volume(self):
        ffmpeg = Path(__file__).resolve().parents[1] / 'cli/ffmpeg.exe'
        if not ffmpeg.is_file():
            self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mp4'
            logo = root / 'logo.ppm'
            logo.write_bytes(b'P6\n4 4\n255\n' + bytes([255, 0, 0]) * 16)
            subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x240:rate=10:duration=1', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=1', '-c:v', 'libx264', '-pix_fmt',
                            'yuv420p', '-c:a', 'aac', '-shortest', str(source)], check=True)
            data = {
                'video_path': str(source), 'out_dir': str(root / 'out'),
                'burn_subs': False, 'burn_vi_subs': False, 'translate_subs': False,
                'voice_convert': False, 'frame_enabled': True, 'frame_title_enabled': True,
                'frame_title': 'Preview test', 'frame_blur_w_pct': 14,
                'frame_blur_top_pct': 9, 'frame_blur_opacity': .6,
                'frame_logo_path': str(logo), 'frame_logo_size_pct': 12, 'vol_orig': 0,
                'skip_ass_review': True, 'skip_ass': True, 'encode_device': 'cpu',
            }
            events = [json.loads(line) for line in process_video_full(data)]
            self.assertFalse([e for e in events if e.get('failed')])
            paths = [e['file_path'] for e in events if e.get('file_path')]
            self.assertTrue(paths and Path(paths[-1]).is_file())
            self.assertNotEqual(Path(paths[-1]), source)
            result = subprocess.run([str(ffmpeg), '-v', 'info', '-i', paths[-1], '-af',
                                     'volumedetect', '-vn', '-f', 'null', '-'], capture_output=True, text=True)
            levels = [line for line in result.stderr.splitlines() if 'max_volume:' in line]
            self.assertTrue(levels and ('-91.0 dB' in levels[0] or '-inf' in levels[0]), levels)
            amplified = root / 'amplified.mp4'
            ok, error = mix_multiple_external_audios(source, [], 2, amplified, str(ffmpeg))
            self.assertTrue(ok, error)
            def mean_volume(path):
                result = subprocess.run([str(ffmpeg), '-v', 'info', '-i', str(path), '-af',
                                         'volumedetect', '-vn', '-f', 'null', '-'], capture_output=True, text=True)
                return float(re.search(r'mean_volume: ([\d.-]+) dB', result.stderr).group(1))
            # RMS gain is stable across AAC encodes; transient peak samples are not.
            self.assertAlmostEqual(mean_volume(amplified) - mean_volume(source), 6.02, delta=.3)


if __name__ == '__main__':
    unittest.main()
