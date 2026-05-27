import sys
sys.path.append('.')
from routes.story import _ai_correct_novel_query
import json

if __name__ == "__main__":
    # Let's override the function locally to use the new prompt
    def _new_ai_correct_novel_query(keyword: str) -> dict:
        from routes.story import _call_llm_multi_tier
        system_msg = """You are a smart Vietnamese web novel expert assistant.
Your task is to identify standard Vietnamese web novel titles and their common alternative names or comic/manga names from user queries.
Users might search using comic names (e.g., 'Đại quản gia là ma hoàng'), typos, or shortened names.
Identify the correct standard text novel title (tiểu thuyết chữ) in Vietnamese (e.g. 'Ma Hoàng Đại Quản Gia') and all popular alternative/comic names (e.g., 'Đại Quản Gia Là Ma Hoàng').

You MUST return strictly a JSON object with this exact schema:
{
  "corrected_title": "standard text novel title in Vietnamese",
  "alternatives": ["alternative name 1", "alternative name 2"],
  "explanation": "Brief explanation in Vietnamese of why it was corrected"
}
Do not include any markdown formatting, code fences, or additional text. Return only the raw JSON string."""

        user_msg = f"User query: '{keyword}'. Return the JSON object now."
        try:
            content = _call_llm_multi_tier(system_msg, user_msg, temperature=0.3, max_tokens=500, json_mode=True)
            if content:
                if "```" in content:
                    import re
                    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
                    if m:
                        content = m.group(1)
                s_idx = content.find("{")
                e_idx = content.rfind("}")
                if s_idx >= 0 and e_idx > s_idx:
                    content = content[s_idx:e_idx + 1]
                import json
                return json.loads(content)
        except Exception as e:
            print("Error during call:", e)
            pass
        return {"corrected_title": keyword, "alternatives": [], "explanation": ""}

    print("--- Correcting 'Đại Quản Gia Là Ma Hoàng' ---")
    res1 = _new_ai_correct_novel_query("Đại Quản Gia Là Ma Hoàng")
    print(json.dumps(res1, indent=2, ensure_ascii=False))

    print("\n--- Correcting 'Ma Hoàng Đại Quản Gia' ---")
    res2 = _new_ai_correct_novel_query("Ma Hoàng Đại Quản Gia")
    print(json.dumps(res2, indent=2, ensure_ascii=False))
