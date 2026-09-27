import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.processor.subtitles import align_subtitles_to_voice, write_ass, write_ass_with_frame


class VoiceTimelineTests(unittest.TestCase):
    def test_mixer_rejects_overlapping_clips_before_encoding(self):
        from core.processor.audio_mixer import AudioMixer
        ok, error = AudioMixer('unused').mix(Path('unused.mp4'),
            [dict(path='a.wav', start=0, duration=2), dict(path='b.wav', start=1, duration=2)],
            Path('unused_output.mp4'), False, 0, 1)
        self.assertFalse(ok)
        self.assertIn('chồng', error)

    def test_silences_and_video_anchors_are_preserved(self):
        rows = [dict(start=2, end=4, text='Xin chào.'), dict(start=8, end=10, text='Chào bạn.')]
        clips = [dict(index=i, path='unused.wav', duration=1.5) for i in range(2)]
        audio, subs = align_subtitles_to_voice(rows, clips, video_duration=10)
        self.assertEqual([c['start'] for c in audio], [2, 8])
        self.assertEqual([c['end'] for c in audio], [3.5, 9.5])
        self.assertEqual([(c['start'], c['end']) for c in audio],
                         [(s['start'], s['end']) for s in subs])

    def test_cannot_ripple_or_cut_long_speech_at_video_end(self):
        rows = [dict(start=8, end=12, text='Câu quá dài.')]
        with self.assertRaisesRegex(ValueError, 'rút gọn'):
            align_subtitles_to_voice(rows, [dict(index=0, path='unused.wav', duration=4)], video_duration=10)

    def test_overlapping_source_windows_fail_instead_of_mixing(self):
        rows = [dict(start=0, end=4, text='Một'), dict(start=1, end=3, text='Hai')]
        clips = [dict(index=i, path='unused.wav', duration=2) for i in range(2)]
        with self.assertRaises(ValueError):
            align_subtitles_to_voice(rows, clips, video_duration=5)

    def test_failed_tempo_correction_does_not_export_bad_timeline(self):
        with patch('core.processor.tts._apply_atempo', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Không điều chỉnh'):
                align_subtitles_to_voice([dict(start=0, end=2, text='Một')],
                                         [dict(index=0, path='unused.wav', duration=2.2)])

    def test_writers_keep_measured_sentence_as_one_event(self):
        rows = [dict(start=1.2, end=4.3, text='Đây là một câu dài hơn bảy từ để kiểm tra đồng bộ giọng đọc.', voice_aligned=True)]
        with tempfile.TemporaryDirectory() as tmp:
            for writer in (write_ass, write_ass_with_frame):
                path = Path(tmp) / 'test.ass'
                writer(rows, path, **({'video_duration': 5} if writer is write_ass_with_frame else {}))
                events = [line for line in path.read_text(encoding='utf-8').splitlines()
                          if line.startswith('Dialogue:') and rows[0]['text'] in line]
                self.assertEqual(len(events), 1)
                self.assertIn('0:00:01.20,0:00:04.30', events[0])

    def test_actual_ffmpeg_tempo_fits_window(self):
        import subprocess
        ffmpeg = Path(__file__).resolve().parents[1] / 'cli/ffmpeg.exe'
        if not ffmpeg.exists():
            self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'speech.wav'
            subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=2.2', str(audio)], check=True)
            clips, rows = align_subtitles_to_voice([dict(start=1, end=3, text='Một câu')],
                [dict(index=0, path=audio)], ffmpeg=str(ffmpeg), video_duration=3)
            self.assertEqual(clips[0]['start'], 1)
            self.assertLessEqual(clips[0]['end'], 3)
            self.assertEqual(clips[0]['end'], rows[0]['end'])

    def test_cached_ass_pipeline_uses_same_timeline_for_burn_and_mix(self):
        import json
        import subprocess
        from core.processor.pipeline import process_video_full
        ffmpeg = Path(__file__).resolve().parents[1] / 'cli/ffmpeg.exe'
        if not ffmpeg.exists():
            self.skipTest('FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mp4'
            subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=blue:s=160x240:r=10:d=4', '-c:v', 'libx264', str(source)], check=True)
            (root / 'source.srt').write_text('1\n00:00:01,000 --> 00:00:03,000\nXin chào.\n', encoding='utf-8')
            write_ass([dict(start=1, end=3, text='Xin chào.')], root / 'source_vi.ass')
            async def generate(provider, segments, translations, tmpdir, **kwargs):
                audio = Path(tmpdir) / 'test.wav'
                subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                                'sine=frequency=440:duration=1', str(audio)], check=True)
                return [dict(index=0, path=audio, start=1, end=3)]
            data = dict(video_path=str(source), out_dir=str(root), burn_subs=True,
                        burn_vi_subs=True, translate_subs=True, voice_convert=True,
                        target_language='vi', frame_enabled=False, frame_title_auto=False,
                        skip_ass_review=True, skip_ass=True, encode_device='cpu', vol_orig=0)
            with patch('core.processor.tts.MultiProviderTTS.generate_all', generate), \
                 patch('core.processor.completed_outputs.register_output'):
                events = [json.loads(line) for line in process_video_full(data)]
            self.assertFalse([e for e in events if e.get('failed')], events)
            synced = root / 'source_vi_voice_sync.ass'
            self.assertTrue(synced.exists(), events)
            self.assertIn('0:00:01.00,0:00:02.00', synced.read_text(encoding='utf-8'))
            # Source translation remains reusable, without accumulating retiming.
            self.assertIn('0:00:01.00,0:00:03.00', (root / 'source_vi.ass').read_text(encoding='utf-8'))
            self.assertTrue(any(e.get('file_path') for e in events))


if __name__ == '__main__':
    unittest.main()
