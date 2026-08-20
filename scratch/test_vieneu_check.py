import sys
from pathlib import Path
from core.video_processor import _tts_vieneu

out = Path("output/test_vieneu_speech.mp3")
out.parent.mkdir(parents=True, exist_ok=True)

print("Testing VieNeu TTS synthesis...")
try:
    ok = _tts_vieneu("Xin chào, đây là bài kiểm tra giọng đọc VieNeu TTS.", voice="Ngọc Linh", out_path=out)
    print("Result ok:", ok)
    if ok and out.exists():
        print(f"Success! Output generated at {out} (size: {out.stat().st_size} bytes)")
    else:
        print("Failed to generate audio file.")
except Exception as e:
    print("Error during VieNeu TTS test:", e)
