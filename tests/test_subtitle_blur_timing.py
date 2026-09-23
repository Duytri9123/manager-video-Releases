import subprocess
import unittest
from pathlib import Path

from core.processor.subtitles import _subtitle_blur_enable


class SubtitleBlurTimingTests(unittest.TestCase):
    def test_continuous_and_empty(self):
        self.assertEqual(_subtitle_blur_enable(None), '')
        self.assertEqual(_subtitle_blur_enable([]), ":enable='0'")

    def test_merge_and_ignore_empty_cues(self):
        cues = [dict(start=2, end=3, text='b'), dict(start=1, end=2.5, text='a'),
                dict(start=4, end=5, text=' '), dict(start=7, end=6, text='bad')]
        self.assertEqual(_subtitle_blur_enable(cues), ":enable='gte(t,1.000)*lt(t,3.000)'")

    def test_many_disjoint_cues_fall_back_to_continuous_blur(self):
        cues = [dict(start=i * 2, end=i * 2 + 1, text=f'cue {i}') for i in range(65)]
        self.assertEqual(_subtitle_blur_enable(cues), '')

    def test_ffmpeg_pixels_change_only_inside_cues(self):
        ffmpeg = Path(__file__).resolve().parents[1] / 'cli' / 'ffmpeg.exe'
        if not ffmpeg.exists():
            self.skipTest('FFmpeg unavailable')
        source = 'testsrc2=s=128x128:r=10:d=1'
        def render(graph):
            result = subprocess.run([str(ffmpeg), '-v', 'error', '-filter_complex_threads', '1',
                                     '-f', 'lavfi', '-i', source, '-filter_complex', graph,
                                     '-map', '[out]', '-pix_fmt', 'yuv420p', '-f', 'rawvideo', '-'],
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            return result.stdout
        base = render('[0:v]null[out]')
        enable = _subtitle_blur_enable([dict(start=.2, end=.5, text='subtitle')])
        masked = render('[0:v]split[a][b];[b]crop=64:64:32:32,boxblur=4[c];'
                        f'[a][c]overlay=32:32{enable}[out]')
        size = 128 * 128 * 3 // 2
        self.assertEqual(len(base), len(masked))
        for frame in range(10):
            original = base[frame*size:(frame+1)*size]
            output = masked[frame*size:(frame+1)*size]
            self.assertEqual(original != output, 2 <= frame < 5, f'frame {frame}')


if __name__ == '__main__':
    unittest.main()
