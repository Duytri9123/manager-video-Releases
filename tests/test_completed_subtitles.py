import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.processor.completed_outputs import register_output, list_outputs, subtitles_for_output


class CompletedSubtitleTests(unittest.TestCase):
    def test_legacy_registry_migration_and_explicit_ass_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'outputs.db'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE outputs (path TEXT PRIMARY KEY, completed REAL NOT NULL)')
            conn.close()
            video, ass = root / 'video.mp4', root / 'voice_sync.ass'
            video.write_bytes(b'video')
            ass.write_text('ASS', encoding='utf-8')
            with patch('core.processor.completed_outputs.DB_PATH', db):
                register_output(video, ass)
                self.assertEqual(list_outputs()[0][0], video.resolve())
                candidates, selected = subtitles_for_output(video)
                self.assertEqual(selected, str(ass.resolve()))
                self.assertIn(selected, candidates)

    def test_old_video_requires_explicit_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'old.mp4'
            video.write_bytes(b'video')
            (root / 'candidate.ass').write_text('ASS', encoding='utf-8')
            with patch('core.processor.completed_outputs.DB_PATH', root / 'outputs.db'):
                register_output(video)
                candidates, selected = subtitles_for_output(video)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(selected, '')
