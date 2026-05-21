import os

import pandas as pd


def parse_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext in (".xlsx", ".xls"):
        return _parse_excel(path)
    if ext == ".csv":
        return _parse_csv(path)
    return ""


def _parse_pdf(path: str) -> str:
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
                for table in page.extract_tables() or []:
                    for row in table:
                        if row:
                            parts.append(" | ".join(str(c) for c in row if c is not None))
        return "\n".join(parts)
    except Exception as e:
        return f"שגיאה בקריאת PDF: {e}"


def _filter_to_recent_year(df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows from the most recent 12 months. If no date found, return as-is."""
    date_col = None
    for col in df.columns:
        try:
            parsed = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
            valid = parsed.dropna()
            if len(valid) >= max(3, len(df) * 0.3):
                date_col = col
                df = df.copy()
                df[col] = parsed
                break
        except Exception:
            continue

    if date_col is None:
        return df

    max_date = df[date_col].max()
    if pd.isnull(max_date):
        return df

    cutoff = max_date - pd.DateOffset(years=1)
    filtered = df[df[date_col] >= cutoff]
    # Only apply filter if it actually reduces the data meaningfully
    if len(filtered) < len(df) * 0.95:
        print(f"[PARSER] filtered {len(df)} → {len(filtered)} rows (most recent year up to {max_date.date()})")
        return filtered
    return df


def _parse_excel(path: str) -> str:
    try:
        dfs = pd.read_excel(path, sheet_name=None)
        parts: list[str] = []
        for sheet_name, df in dfs.items():
            df = _filter_to_recent_year(df)
            parts.append(f"=== גיליון: {sheet_name} ===")
            parts.append(df.to_string(index=False))
        return "\n".join(parts)
    except Exception as e:
        return f"שגיאה בקריאת Excel: {e}"


def _parse_csv(path: str) -> str:
    for enc in ("utf-8-sig", "windows-1255", "latin-1"):
        try:
            df = pd.read_csv(path, encoding=enc)
            df = _filter_to_recent_year(df)
            return df.to_string(index=False)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"שגיאה בקריאת CSV: {e}"
    return "שגיאה: לא ניתן לפענח את הקובץ"
