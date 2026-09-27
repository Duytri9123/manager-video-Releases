import unittest

from core.processor.subtitles import _merge_segments_for_tts, _smart_split_display_lines


class SentenceBoundariesTests(unittest.TestCase):
    def test_display_does_not_mix_end_and_next_sentence(self):
        self.assertEqual(_smart_split_display_lines('mất hết vị ngọt tươi. Hôm nay'),
                         ['mất hết vị ngọt tươi.', 'Hôm nay'])

    def test_tts_reconstructs_sentences_from_old_ass_rows(self):
        rows = [
            {'start': 0, 'end': 2, 'text': 'Làm như vậy sẽ'},
            {'start': 2.01, 'end': 5, 'text': 'mất hết vị ngọt tươi. Hôm nay'},
            {'start': 5.01, 'end': 8, 'text': 'chúng ta cùng nấu ăn.'},
        ]
        result = _merge_segments_for_tts(rows)
        self.assertEqual([s['text'] for s in result], [
            'Làm như vậy sẽ mất hết vị ngọt tươi.', 'Hôm nay chúng ta cùng nấu ăn.'])
        self.assertEqual(result[0]['start'], 0)
        self.assertEqual(result[-1]['end'], 8)
        self.assertLessEqual(result[0]['end'], result[1]['start'])

    def test_no_word_limit_break_in_unfinished_sentence(self):
        result = _merge_segments_for_tts([
            {'start': 0, 'end': 3, 'text': 'Hôm nay chúng ta cùng'},
            {'start': 3.7, 'end': 6, 'text': 'nấu một món ăn ngon.'},
        ], max_words=3, max_chars=10)
        self.assertEqual(len(result), 1)

    def test_preserve_speaker_boundary(self):
        result = _merge_segments_for_tts([
            {'start': 0, 'end': 1, 'text': 'Xin chào', 'speaker': 'male'},
            {'start': 1, 'end': 2, 'text': 'chào bạn.', 'speaker': 'female'},
        ])
        self.assertEqual(len(result), 2)


if __name__ == '__main__':
    unittest.main()
