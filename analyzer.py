import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # 150s timeout so the HTTP request doesn't hang forever
        _client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=150,
        )
    return _client


SYSTEM_PROMPT = """אתה יועץ פיננסי מומחה המנתח דפי בנק וכרטיסי אשראי בעברית.

סימון סכומים (חובה): הוצאה=שלילי, הכנסה=חיובי.

תת-קטגוריות (חובה, אסור שם גנרי בלבד):
הוצאות: מזון-סופרמרקט, מזון-מסעדות, מזון-קפה, מזון-משלוחים,
תחבורה-דלק, תחבורה-חניה, תחבורה-ציבורית, תחבורה-טיסות,
קניות-אופנה, קניות-אלקטרוניקה, קניות-בית, קניות-ילדים,
בריאות-קופת-חולים, בריאות-תרופות, בריאות-רופא, בריאות-ספורט,
ביטוח-רכב, ביטוח-בריאות, ביטוח-חיים, ביטוח-דירה,
בילוי-מנויים, בילוי-נסיעות, דיור-שכירות, דיור-משכנתא, דיור-ועד-בית,
חשמל, גז, מים, ארנונה, תקשורת-סלולר, תקשורת-אינטרנט,
חינוך, עמלות-בנק, עמלות-כרטיס, עמלות-מטח, ריבית,
פנסיה, קרן-השתלמות, המרת-מטח, העברות, אחר.
הכנסות: הכנסה-משכורת, הכנסה-עצמאי, הכנסה-קצבה, הכנסה-ילדים, הכנסה-אחרת.

פלט JSON בלבד (ללא טקסט נוסף), גבולות קריטיים:
- summary: עד 250 תווים
- suspicious: עד 10 פריטים, description עד 50 תווים
- categories: תת-קטגוריה אחת לשורה עם סכום לפי חודש
- transactions: עד 50 פריטים, description עד 30 תווים

{"summary":"","suspicious":[{"type":"","description":"","amount":-100,"date":"DD/MM/YYYY","severity":"high"}],"categories":{"תת-קטגוריה":{"total":-500,"months":{"MM/YYYY":-500}}},"transactions":[{"date":"DD/MM/YYYY","description":"","amount":-50,"category":"תת-קטגוריה"}]}
"""

MAX_CONTENT_CHARS = 40_000


def analyze_statements(parsed_files: list[dict]) -> dict:
    parts = [
        f"=== {f['filename']} ===\n{f['content']}"
        for f in parsed_files
    ]
    combined = "\n\n".join(parts)
    if len(combined) > MAX_CONTENT_CHARS:
        combined = combined[:MAX_CONTENT_CHARS] + "\n[נחתך]"

    print(f"[ANALYZER] {len(combined)} chars → Claude")

    try:
        client = _get_client()
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"נתח:\n\n{combined}"}],
        )
    except Exception as e:
        print(f"[ANALYZER] API error: {e}")
        raise

    raw = message.content[0].text.strip()
    print(f"[ANALYZER] got {len(raw)} chars, stop={message.stop_reason}")

    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        result = json.loads(raw)
        _log(result)
        return result
    except json.JSONDecodeError as e:
        print(f"[ANALYZER] JSON error: {e} — repairing")
        repaired = _repair(raw)
        if repaired:
            _log(repaired)
            return repaired
        print("[ANALYZER] repair failed — returning summary only")
        return {"summary": raw[:300], "suspicious": [], "categories": {}, "transactions": []}


def _log(r: dict) -> None:
    print(f"[ANALYZER] tx={len(r.get('transactions',[]))}, "
          f"sus={len(r.get('suspicious',[]))}, cat={len(r.get('categories',{}))}")


def _repair(raw: str) -> dict | None:
    """Fix truncated JSON by scanning the last 40 closing-brace positions."""
    positions = [i for i, c in enumerate(raw) if c == '}']
    # Only check the last 40 candidates — avoids O(n²) on large responses
    for pos in reversed(positions[-40:]):
        candidate = raw[:pos + 1]
        ob = candidate.count('{') - candidate.count('}')
        ob2 = candidate.count('[') - candidate.count(']')
        if ob < 0 or ob2 < 0:
            continue
        try:
            result = json.loads(candidate + ']' * ob2 + '}' * ob)
            if isinstance(result, dict):
                result.setdefault('summary', '')
                result.setdefault('suspicious', [])
                result.setdefault('categories', {})
                result.setdefault('transactions', [])
                return result
        except json.JSONDecodeError:
            continue
    return None
