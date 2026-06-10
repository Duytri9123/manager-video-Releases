from core.video_processor import _merge_segments_for_tts


def test_merge_uses_eight_second_windows_across_sentence_boundaries():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "First sentence."},
        {"start": 2.01, "end": 4.0, "text": "Second sentence."},
        {"start": 4.01, "end": 7.99, "text": "Third sentence."},
        {"start": 8.0, "end": 9.0, "text": "Fourth sentence."},
    ]

    merged = _merge_segments_for_tts(segments)

    assert len(merged) == 2
    assert merged[0]["start"] == 0.0
    assert merged[0]["end"] == 7.99
    assert merged[0]["text"] == "First sentence. Second sentence. Third sentence."
    assert merged[1]["text"] == "Fourth sentence."


def test_merge_keeps_real_timeline_gaps_separate():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Before gap."},
        {"start": 2.2, "end": 4.0, "text": "After gap."},
    ]

    assert len(_merge_segments_for_tts(segments)) == 2
