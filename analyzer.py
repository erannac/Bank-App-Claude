import json
import os
import re

import anthropic
from dotenv import load_dotenv

load_dotenv()

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


SYSTEM_PROMPT = """אתה יועץ פיננסי מומחה המנתח דפי בנק וכרטיסי אשראי בעברית.

סימון סכומים (חובה לכל המקטעים):
- הוצאה: סכום שלילי, למשל -250.50
- הכנסה: סכום חיובי, למשל 5000.00

תת-קטגוריות (חובה — אסור "קניות" סתם, חייב פירוט):
הוצאות: מזון-סופרמרקט, מזון-מסעדות, מזון-קפה, מזון-משלוחים,
תחבורה-דלק, תחבורה-חניה, תחבורה-ציבורית, תחבורה-טיסות,
קניות-אופנה, קניות-אלקטרוניקה, קניות-בית, קניות-ילדים, קניות-מתנות,
בריאות-קופת-חולים, בריאות-תרופות, בריאות-רופא, בריאות-ספורט,
ביטוח-רכב, ביטוח-בריאות, ביטוח-חיים, ביטוח-דירה,
בילוי-מנויים, בילוי-נסיעות, בילוי-קולנוע,
דיור-שכירות, דיור-משכנתא, דיור-ועד-בית,
חשמל, גז, מים, ארנונה, תקשורת-סלולר, תקשורת-אינטרנט,
חינוך, עמלות-בנק, עמלות-כרטיס, עמלות-מטח, ריבית,
פנסיה, קרן-השתלמות, המרת-מטח, העברות, אחר.
הכנסות: הכנסה-משכורת, הכנסה-עצמאי, הכנסה-קצבה, הכנסה-ילדים, הכנסה-אחרת.

הנחיות:
1. עד 15 ממצאים חשודים (suspicious).
2. categories: תת-קטגוריה אחת לשורה, סכום לפי חודש.
3. עד 60 תנועות (transactions), description עד 35 תווים.

גבולות: summary≤300 תווים, suspicious.description≤60 תווים.

ענה JSON בלבד:
{"summary":"","suspicious":[{"type":"","description":"","amount":-100,"date":"DD/MM/YYYY","severity":"high"}],"categories":{"תת-קטגוריה":{"total":-500,"months":{"MM/YYYY":-500}}},"transactions":[{"date":"DD/MM/YYYY","description":"","amount":-50,"category":"תת-קטגוריה"}]}
"""

MAX_CONTENT_CHARS = 60_000


def analyze_statements(parsed_files: list[dict]) -> dict:
    parts = [
        f"=== קובץ: {f['filename']} ===\n{f['content']}"
        for f in parsed_files
    ]
    combined = "\n\n".join(parts)
    if len(combined) > MAX_CONTENT_CHARS:
        combined = combined[:MAX_CONTENT_CHARS] + "\n\n[... תוכן נחתך ...]"

    print(f"[ANALYZER] sending {len(combined)} chars to Claude.")

    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"נתח:\n\n{combined}"}],
    )

    raw = message.content[0].text.strip()
    print(f"[ANALYZER] response {len(raw)} chars. stop_reason={message.stop_reason}")

    # Strip markdown fences
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        result = json.loads(raw)
        _log_result(result)
        return result
    except json.JSONDecodeError as e:
        print(f"[ANALYZER] JSON error: {e} — attempting repair")
        repaired = _repair_truncated_json(raw)
        if repaired:
            _log_result(repaired)
            return repaired
        print(f"[ANALYZER] repair failed.")
        return {"summary": raw[:400], "suspicious": [], "categories": {}, "transactions": []}


def _log_result(r: dict) -> None:
    print(f"[ANALYZER] OK — tx={len(r.get('transactions', []))}, "
          f"sus={len(r.get('suspicious', []))}, cat={len(r.get('categories', {}))}")


def _repair_truncated_json(raw: str) -> dict | None:
    """Salvage JSON cut off mid-stream by scanning backwards for the last complete object."""
    # Walk backwards through every '}' position and try to close the structure
    positions = [i for i, c in enumerate(raw) if c == '}']
    for pos in reversed(positions):
        candidate = raw[:pos + 1]
        open_braces = candidate.count('{') - candidate.count('}')
        open_brackets = candidate.count('[') - candidate.count(']')
        if open_braces < 0 or open_brackets < 0:
            continue
        closing = ']' * open_brackets + '}' * open_braces
        try:
            result = json.loads(candidate + closing)
            if isinstance(result, dict):
                result.setdefault('summary', '')
                result.setdefault('suspicious', [])
                result.setdefault('categories', {})
                result.setdefault('transactions', [])
                return result
        except json.JSONDecodeError:
            continue
    return None
