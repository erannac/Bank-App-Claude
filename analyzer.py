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

חובה לבצע:
1. זהה עד 15 ממצאים חשודים (חיובים כפולים, עמלות חריגות, חודשים חסרים, הוצאות חריגות).
2. סכם הוצאות לפי קטגוריה וחודש — קטגוריות: מזון, דלק, ביטוח, שכר דירה, בילוי, בריאות, קניות, עמלות, הכנסות, אחר.
3. חלץ עד 80 תנועות מייצגות (העדף חשודות, גדולות, או קבועות). תיאורים קצרים עד 40 תווים.

חוקים קריטיים לגודל הפלט:
- summary: עד 400 תווים
- suspicious: עד 15 פריטים, description עד 80 תווים
- transactions: עד 80 פריטים, description עד 40 תווים
- categories: סכם לפי חודש בלבד (ללא פירוט נוסף)

ענה ב-JSON בלבד, ללא טקסט נוסף:
{
  "summary": "סיכום קצר",
  "suspicious": [
    {"type": "סוג", "description": "תיאור קצר", "amount": 0, "date": "DD/MM/YYYY", "severity": "high"}
  ],
  "categories": {
    "קטגוריה": {"total": 0, "months": {"MM/YYYY": 0}}
  },
  "transactions": [
    {"date": "DD/MM/YYYY", "description": "תיאור קצר", "amount": 0, "category": "קטגוריה"}
  ]
}

severity: "high" / "medium" / "low" בלבד.
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
