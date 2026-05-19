import json
import os

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

=== כללי סימון סכומים (חובה) ===
- הוצאה (כסף יוצא מהחשבון): סכום שלילי, למשל -250.50
- הכנסה (כסף נכנס לחשבון): סכום חיובי, למשל 5000.00
חוק זה חל על שלושת המקטעים: suspicious, categories, transactions.

=== תת-קטגוריות (חובה) ===
חייב להשתמש בתת-קטגוריות מפורטות. אסור להשתמש בשמות גנריים כמו "קניות" או "אחר" בלבד.
רשימת התת-קטגוריות המותרות (הוסף לפי הצורך):

הוצאות:
- מזון-סופרמרקט, מזון-מסעדות, מזון-קפה, מזון-משלוחים
- תחבורה-דלק, תחבורה-חניה, תחבורה-ציבורית, תחבורה-מונית, תחבורה-טיסות
- קניות-אופנה, קניות-אלקטרוניקה, קניות-רהיטים, קניות-ספרים, קניות-ילדים, קניות-מתנות
- בריאות-קופת-חולים, בריאות-תרופות, בריאות-רופא-פרטי, בריאות-ספורט
- ביטוח-רכב, ביטוח-בריאות, ביטוח-חיים, ביטוח-דירה
- בילוי-קולנוע, בילוי-ספורט, בילוי-נסיעות, בילוי-מנויים
- תשלומי-דירה-שכירות, תשלומי-דירה-משכנתא, תשלומי-דירה-ועד-בית
- חשמל, גז, מים, ארנונה
- תקשורת-סלולר, תקשורת-אינטרנט, תקשורת-טלוויזיה
- חינוך-שכר-לימוד, חינוך-גן, חינוך-קורסים
- עמלות-בנק, עמלות-כרטיס-אשראי, עמלות-מטח, ריבית
- פנסיה, קרן-השתלמות, ביטוח-לאומי
- העברות-לאחרים, המרת-מטח

הכנסות:
- הכנסה-משכורת, הכנסה-עצמאי, הכנסה-קצבה, הכנסה-ילדים, הכנסה-שכר-דירה, הכנסה-אחרת

=== הנחיות ===
1. זהה עד 15 ממצאים חשודים.
2. סכם לפי תת-קטגוריה וחודש — כל תת-קטגוריה שורה נפרדת.
3. חלץ עד 80 תנועות מייצגות, description עד 40 תווים.

גבולות גודל:
- summary: עד 400 תווים
- suspicious: עד 15, description עד 80 תווים
- transactions: עד 80, description עד 40 תווים

ענה ב-JSON בלבד, ללא טקסט נוסף:
{
  "summary": "סיכום",
  "suspicious": [{"type":"","description":"","amount":-100,"date":"DD/MM/YYYY","severity":"high"}],
  "categories": {"תת-קטגוריה": {"total": -500, "months": {"MM/YYYY": -500}}},
  "transactions": [{"date":"DD/MM/YYYY","description":"","amount":-50,"category":"תת-קטגוריה"}]
}

severity: "high"/"medium"/"low" בלבד.
"""

MAX_CONTENT_CHARS = 80_000


def analyze_statements(parsed_files: list[dict]) -> dict:
    parts = [
        f"=== קובץ: {f['filename']} ===\n{f['content']}"
        for f in parsed_files
    ]
    combined = "\n\n".join(parts)
    if len(combined) > MAX_CONTENT_CHARS:
        combined = combined[:MAX_CONTENT_CHARS] + "\n\n[... תוכן נחתך בגלל אורך ...]"

    print(f"[ANALYZER] sending {len(combined)} chars to Claude. Preview:\n{combined[:1000]}\n---")

    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"נתח את דפי הבנק/כרטיס האשראי הבאים:\n\n{combined}",
            }
        ],
    )

    raw = message.content[0].text.strip()
    print(f"[ANALYZER] Claude raw response ({len(raw)} chars):\n{raw[:2000]}\n---")

    # Strip markdown code fences if present
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        result = json.loads(raw)
        print(f"[ANALYZER] parsed OK — transactions={len(result.get('transactions',[]))}, suspicious={len(result.get('suspicious',[]))}, categories={len(result.get('categories',{}))}")
        return result
    except json.JSONDecodeError as e:
        print(f"[ANALYZER] JSON parse error: {e} — attempting repair")
        repaired = _repair_truncated_json(raw)
        if repaired:
            print(f"[ANALYZER] repair OK — transactions={len(repaired.get('transactions',[]))}, suspicious={len(repaired.get('suspicious',[]))}")
            return repaired
        print(f"[ANALYZER] repair failed. Raw[:300]: {raw[:300]}")
        return {
            "summary": raw[:500],
            "suspicious": [],
            "categories": {},
            "transactions": [],
        }


def _repair_truncated_json(raw: str) -> dict | None:
    """Try to salvage a JSON that was cut off mid-stream due to token limits."""
    # Remove the last incomplete item by trimming to the last complete object
    # Strategy: find the last occurrence of '}' that closes a list item,
    # then close all open structures.
    for close_char in ('}', ']'):
        idx = raw.rfind(close_char)
        if idx == -1:
            continue
        candidate = raw[:idx + 1]
        # Count unmatched open braces/brackets and close them
        open_braces = candidate.count('{') - candidate.count('}')
        open_brackets = candidate.count('[') - candidate.count(']')
        if open_braces < 0 or open_brackets < 0:
            continue
        candidate += '}' * open_braces + ']' * open_brackets
        # Try adding the minimum closing to make valid JSON
        for suffix in ['', '}', ']}', ']}}}', ']}]}}']:
            try:
                result = json.loads(candidate + suffix)
                if isinstance(result, dict):
                    result.setdefault('summary', '')
                    result.setdefault('suspicious', [])
                    result.setdefault('categories', {})
                    result.setdefault('transactions', [])
                    return result
            except json.JSONDecodeError:
                continue
    return None
