import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("ai_service_test", Path(__file__).resolve().parents[1] / "templates/pages/process/ai_service.py")
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)

class AnalysisTests(unittest.TestCase):
    def test_title_array_and_invalid_zone_shape(self):
        result = ai.clean_ai_result({"title_suggestions": ["Title"], "suggested_blur_zones": "invalid"})
        self.assertEqual(result["title_suggestions"]["short"], "Title")
        self.assertEqual(result["suggested_blur_zones"], [])

    def test_batches_cover_all_frames_and_bound_masks(self):
        calls = []
        def call(prompt, frames):
            calls.append(len(frames))
            return {"summary": "Story", "suggested_blur_zones": [{"start_sec": 0, "end_sec": 100, "confidence": .95}]}
        result = ai.analyze_video_batches([{"timestamp": i + .5} for i in range(25)], 25, "auto", "vi", call)
        self.assertEqual(calls, [12, 12, 1, 0])
        self.assertEqual([(z["start_sec"], z["end_sec"]) for z in result["suggested_blur_zones"]], [(0, 12), (12, 24), (24, 25)])
