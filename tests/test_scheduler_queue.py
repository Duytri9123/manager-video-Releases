"""Queue regressions with an isolated database and no network/publishing."""
import importlib.util
import json
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]


class ScheduleQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        core_app = types.ModuleType('core_app')
        core_app.ROOT = self.root
        core_app.STATE_DIR = self.root
        core_app.LOGGER = logging.getLogger('scheduler-test')
        spec = importlib.util.spec_from_file_location('scheduler_under_test', ROOT / 'templates/pages/scheduler/route.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'core_app': core_app}):
            spec.loader.exec_module(self.module)
        self.app = Flask(__name__)
        self.app.testing = True
        self.app.register_blueprint(self.module.bp)
        self.client = self.app.test_client()
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'test')

    def tearDown(self):
        self.temp.cleanup()

    def add(self, when='2099-01-01T10:00', config=None):
        response = self.client.post('/api/scheduler/items', json={
            'source_url': str(self.source), 'scheduled_at': when,
            'processing': config or {'frame_enabled': True, 'vol_orig': 0},
            'platform': 'tiktok',
        })
        self.assertEqual(response.status_code, 201)
        return response.json['ids'][0]

    def item(self, item_id):
        return next(x for x in self.client.get('/api/scheduler/items').json['items'] if x['id'] == item_id)

    def test_new_schedule_queues_immediately_and_snapshots_full_config(self):
        config = {'vol_orig': 0, 'frame_title_enabled': False, 'frame_logo_path': 'logo.png', 'ext_audios': [{'vol': .2}], 'target_aspect': '16x9'}
        item = self.item(self.add(config=config))
        self.assertEqual(item['status'], 'queued')
        self.assertEqual(item['processing'], config)

    def test_process_errors_are_not_swallowed_or_replaced_with_source(self):
        item_id = self.add()
        processor = types.ModuleType('core.video_processor')
        processor.process_video_full = Mock(return_value=iter([json.dumps({'failed': True, 'log': 'encode failed'})]))
        with patch.dict(sys.modules, {'core.video_processor': processor}):
            self.module._run_processing_job(item_id)
        item = self.item(item_id)
        self.assertEqual(item['status'], 'failed')
        self.assertEqual(item['error'], 'encode failed')
        self.assertFalse(item['video_path'])
        self.assertEqual(processor.process_video_full.call_args.args[0]['vol_orig'], 0)

    def test_no_output_is_failure(self):
        item_id = self.add()
        processor = types.ModuleType('core.video_processor')
        processor.process_video_full = Mock(return_value=iter([]))
        with patch.dict(sys.modules, {'core.video_processor': processor}):
            self.module._run_processing_job(item_id)
        self.assertEqual(self.item(item_id)['status'], 'failed')

    def test_scheduler_uses_same_downloader_as_manual_processing(self):
        item_id = self.add()
        self.client.patch(f'/api/scheduler/items/{item_id}', json={'source_url':'https://www.douyin.com/video/123'})
        output = self.root / 'output.mp4'
        output.write_bytes(b'rendered')
        download = types.ModuleType('templates.pages.process.route')
        download.download_original_source = Mock(return_value=(self.source, 'Video title'))
        processor = types.ModuleType('core.video_processor')
        processor.process_video_full = Mock(return_value=iter([json.dumps({'file_path':str(output)})]))
        with patch.dict(sys.modules, {'templates.pages.process.route':download, 'core.video_processor':processor}):
            self.module._run_processing_job(item_id)
        download.download_original_source.assert_called_once_with('https://www.douyin.com/video/123')
        self.assertEqual(self.item(item_id)['status'], 'ready')
        self.assertEqual(processor.process_video_full.call_args.args[0]['video_title'], 'Video title')

    def test_queue_prepares_earliest_first_without_publishing_future_item(self):
        later = self.add('2099-02-01T10:00')
        earlier = self.add('2099-01-01T10:00')
        with patch.object(self.module, '_run_processing_job') as process, patch.object(self.module, '_run_publishing_job') as publish:
            self.assertTrue(self.module._schedule_tick())
            process.assert_called_once_with(earlier)
            publish.assert_not_called()
        self.assertNotEqual(later, earlier)

    def test_duplicate_process_and_premature_publish_rejected(self):
        item_id = self.add()
        self.assertEqual(self.client.post(f'/api/scheduler/items/{item_id}/process').status_code, 409)
        self.assertEqual(self.client.post(f'/api/scheduler/items/{item_id}/publish').status_code, 409)

    def test_due_ready_item_publishes_before_next_download(self):
        due = self.add('2020-01-01T10:00')
        self.client.patch(f'/api/scheduler/items/{due}', json={'status': 'ready', 'video_path': str(self.source)})
        self.add()
        with patch.object(self.module, '_run_processing_job') as process, patch.object(self.module, '_run_publishing_job') as publish:
            self.assertTrue(self.module._schedule_tick())
            publish.assert_called_once_with(due)
            process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
