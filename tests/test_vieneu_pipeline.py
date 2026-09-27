import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.processor.tts import MultiProviderTTS
from core.tts_catalog import local_tts_engines, resolve_engine_voice


class VieNeuTests(unittest.TestCase):
    def test_only_vieneu_and_canonical_names(self):
        self.assertEqual([e['id'] for e in local_tts_engines()], ['vieneu', 'vieneu-cpu', 'vieneu-gpu', 'vieneu-nano'])
        self.assertEqual(resolve_engine_voice('edge-tts', 'Minh Quân Pro', 'vi')[:2], ('vieneu', local_tts_engines()[0]['default']))

    def test_selected_model_reaches_synthesizer(self):
        for engine in local_tts_engines():
            with self.subTest(engine=engine['id']), patch('core.processor.tts._tts_vieneu', return_value=True) as generate:
                provider = MultiProviderTTS(engine=engine['id'], voice=engine['default'])
                asyncio.run(provider.generate('Xin chào', Path('unused.wav')))
                self.assertEqual(generate.call_args.kwargs['engine'], engine['id'])
                self.assertEqual(generate.call_args.args[1], engine['default'])

    def test_unknown_saved_voice_resolves_to_installed_preset(self):
        engine = local_tts_engines()[0]
        voices = {row[0] for row in engine['voices']['vi']}
        self.assertIn(engine['default'], voices)
        self.assertIn(resolve_engine_voice('vieneu', 'removed-voice', 'vi')[1], voices)

    def test_wav_duration_does_not_decode_with_ffmpeg(self):
        import wave
        from core.processor.tts import _get_audio_duration
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'duration.wav'
            with wave.open(str(path), 'wb') as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(16000)
                out.writeframes(b'\0\0' * 16000)
            with patch('core.processor.tts.subprocess.run', side_effect=AssertionError('unnecessary decode')):
                self.assertEqual(_get_audio_duration('ffmpeg', path), 1.0)

    def test_legacy_engine_cannot_call_external_tts(self):
        with patch('core.processor.tts._tts_vieneu', return_value=True) as generate:
            provider = MultiProviderTTS(engine='edge-tts', voice='Minh Quân Pro')
            self.assertTrue(asyncio.run(provider.generate('Xin chào', Path('unused.wav'))))
            self.assertEqual(generate.call_args.args[1], local_tts_engines()[0]['default'])

    def test_wav_progress_and_female_speaker_not_male(self):
        seen = []
        def synth(text, voice, path, **kwargs):
            seen.append((voice, Path(path).suffix))
            Path(path).write_bytes(b'audio')
            return True
        with tempfile.TemporaryDirectory() as tmp, patch('core.processor.tts._tts_vieneu', side_effect=synth):
            provider = MultiProviderTTS(voice='Minh Quân Pro')
            progress = []
            clips = asyncio.run(provider.generate_all(
                [{'start':0,'end':2,'speaker':'female_1'}, {'start':2,'end':4,'speaker':'male_1'}],
                ['Xin chào', 'Chào bạn'], Path(tmp), auto_speed=False,
                voice_map={'male':'Minh Quân Pro','female':'Trúc Ly'},
                progress_callback=lambda done,total: progress.append((done,total))))
            self.assertEqual(seen, [('Trúc Ly','.wav'),(local_tts_engines()[0]['default'],'.wav')])
            self.assertEqual(progress, [(1,2),(2,2)])
            self.assertEqual(len(clips),2)

    def test_model_failure_is_not_swallowed(self):
        with patch('core.processor.tts._tts_vieneu', side_effect=RuntimeError('model unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'model unavailable'):
                asyncio.run(MultiProviderTTS().generate('test',Path('unused.wav')))


if __name__ == '__main__':
    unittest.main()
