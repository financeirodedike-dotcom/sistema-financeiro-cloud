import hashlib
import re
from datetime import date


def _tag(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)(?:<|\r|\n)", block, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _date(value: str) -> date | None:
    if not value or len(value) < 8:
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _amount(value: str) -> float:
    try:
        return float((value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _decode(content: bytes) -> str:
    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = content.decode("latin1", errors="replace")
    return text


def parse_ofx_balances(content: bytes) -> dict:
    text = _decode(content)
    start_date = _date(_tag(text, "DTSTART"))
    end_date = _date(_tag(text, "DTEND"))
    ledger_block = re.search(r"<LEDGERBAL>(.*?)</LEDGERBAL>", text, flags=re.IGNORECASE | re.DOTALL)
    available_block = re.search(r"<AVAILBAL>(.*?)</AVAILBAL>", text, flags=re.IGNORECASE | re.DOTALL)
    balance_block = ledger_block.group(1) if ledger_block else available_block.group(1) if available_block else ""
    closing_balance = _amount(_tag(balance_block, "BALAMT")) if balance_block else None
    balance_date = _date(_tag(balance_block, "DTASOF")) if balance_block else None
    return {
        "start_date": start_date,
        "end_date": end_date or balance_date,
        "closing_balance": closing_balance,
        "balance_source": "LEDGERBAL" if ledger_block else "AVAILBAL" if available_block else "",
    }


def parse_ofx(content: bytes, filename: str) -> list[dict]:
    text = _decode(content)

    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, flags=re.IGNORECASE | re.DOTALL)
    rows = []

    for block in blocks:
        amount = _amount(_tag(block, "TRNAMT"))
        posted = _date(_tag(block, "DTPOSTED") or _tag(block, "DTUSER"))
        if posted is None:
            continue
        name = _tag(block, "NAME")
        memo = _tag(block, "MEMO")
        history = " - ".join(part for part in (name, memo) if part) or _tag(block, "TRNTYPE")
        fitid = _tag(block, "FITID")
        if not fitid:
            fingerprint = f"{posted.isoformat()}|{amount:.2f}|{history}"
            fitid = "generated:" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
        rows.append(
            {
                "date": posted,
                "history": history,
                "bank": filename,
                "fitid": fitid,
                "amount": amount,
                "entrada": amount if amount > 0 else 0,
                "saida": abs(amount) if amount < 0 else 0,
                "person": "",
                "notes": f"Importado de {filename}",
            }
        )
    return rows
