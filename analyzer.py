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
תפקידך לזהות:
1. חיובים כפולים – אותו סכום לאותו גורם באותו חודש פעמיים או יותר
2. עמלות חריגות – עמלות גבוהות מהרגיל או עמלות בלתי צפויות
3. חודשים חסרים – תשלומים קבועים שדילגו על חודש מסוים
4. הוצאות חריגות – הוצאות גבוהות משמעותית מהממוצע

ענה תמיד ב-JSON בלבד ללא כל טקסט נוסף, בפורמט המדויק הבא:
{
  "summary": "סיכום קצר של הממצאים העיקריים בעברית",
  "suspicious": [
    {
      "type": "סוג הבעיה",
      "description": "תיאור מפורט",
      "amount": 0,
      "date": "תאריך אם ידוע",
      "severity": "high"
    }
  ],
  "categories": {
    "שם קטגוריה": {
      "total": 0,
      "months": {"01/2025": 0}
    }
  },
  "transactions": [
    {
      "date": "תאריך",
      "description": "תיאור",
      "amount": 0,
      "category": "קטגוריה"
    }
  ]
}

severity חייב להיות אחד מ: "high", "medium", "low".
אם אין תנועות חשודות, החזר רשימה ריקה.
אם אין קטגוריות, החזר אובייקט ריק.
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

    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"נתח את דפי הבנק/כרטיס האשראי הבאים:\n\n{combined}",
            }
        ],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "summary": raw[:500],
            "suspicious": [],
            "categories": {},
            "transactions": [],
        }
