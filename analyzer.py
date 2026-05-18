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

חובה לבצע את כל הפעולות הבאות:

1. חלץ את כל התנועות הפיננסיות מהקובץ לרשימת "transactions" – כל שורה עם תאריך וסכום היא תנועה.
2. סווג כל תנועה לקטגוריה (מזון, דלק, ביטוח, שכר דירה, בילוי, בריאות, קניות, עמלות, אחר).
3. סכם הוצאות לפי קטגוריה וחודש ב-"categories".
4. זהה ב-"suspicious":
   - חיובים כפולים – אותו סכום לאותו גורם פעמיים+
   - עמלות חריגות – עמלות גבוהות או בלתי צפויות
   - חודשים חסרים בתשלומים קבועים
   - הוצאות גבוהות משמעותית מהממוצע

חוק ברזל: גם אם הנתונים נראים חלקיים – חלץ כל מה שאפשר. אל תחזיר arrays ריקות אם יש נתונים בקובץ.

ענה ב-JSON בלבד, ללא טקסט נוסף, בפורמט המדויק:
{
  "summary": "סיכום ממצאים בעברית",
  "suspicious": [
    {"type": "סוג", "description": "תיאור", "amount": 0, "date": "תאריך", "severity": "high"}
  ],
  "categories": {
    "קטגוריה": {"total": 0, "months": {"MM/YYYY": 0}}
  },
  "transactions": [
    {"date": "DD/MM/YYYY", "description": "תיאור", "amount": 0, "category": "קטגוריה"}
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
        print(f"[ANALYZER] JSON parse error: {e}\nRaw: {raw[:500]}")
        return {
            "summary": raw[:500],
            "suspicious": [],
            "categories": {},
            "transactions": [],
        }
