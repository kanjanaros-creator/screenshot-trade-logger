# parser_engine.py
import re
import yaml
from typing import Dict, Any

# โหลดแพตเทิร์นและ config
with open("parser_patterns.yaml", "r", encoding="utf-8") as f:
    PAT = yaml.safe_load(f)
with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)


def _first_match(patterns, text: str, group_name: str = None):
    """คืนค่าจาก regex กลุ่มแรกที่เจอ (แบบ case-insensitive)"""
    if not text:
        return None
    for pat in patterns or []:
        m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        if not m:
            continue
        if group_name:
            gd = m.groupdict()
            if group_name in gd and gd[group_name] is not None:
                return gd[group_name]
        else:
            return m.group(0)
    return None


def guess_exchange(text: str) -> str:
    t = text.lower()
    for ex, keys in (CFG.get("exchange_keywords") or {}).items():
        if any(k.lower() in t for k in keys):
            return ex
    return "unknown"


def _normalize_pair(text_pair: str, base_only: str = None, base: str = None, quote: str = None):
    """จัดรูปแบบ pair ให้เป็น BASE/QUOTE"""
    if text_pair:
        up = text_pair.upper().replace(" ", "")
        if "/" not in up and quote:
            return f"{up}/{quote.upper()}"
        return up
    if base and quote:
        return f"{base.upper()}/{quote.upper()}"
    if base_only and quote:
        return f"{base_only.upper()}/{quote.upper()}"
    if base_only:
        return f"{base_only.upper()}/USDT"
    return None


def _num(x):
    if x is None:
        return None
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def parse_trade_from_text(text: str) -> Dict[str, Any]:
    """พยายามดึง trade จากข้อความสลิปแลกเหรียญ/เทรด"""
    # ---------- 1) Binance Convert "Successful" ----------
    qty = _first_match(PAT.get("convert_receive_patterns", []), text, "qty")
    base = _first_match(PAT.get("convert_receive_patterns", []), text, "base")

    inv_units = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "units")
    inv_quote = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "quote")

    dir_units = _first_match(PAT.get("convert_direct_price_patterns", []), text, "units")
    dir_quote = _first_match(PAT.get("convert_direct_price_patterns", []), text, "quote")

    tx_amount = _first_match(PAT.get("convert_tx_amount_patterns", []), text, "amount")
    tx_quote = _first_match(PAT.get("convert_tx_amount_patterns", []), text, "quote")

    if qty and base and (inv_units and (inv_quote or tx_quote)):
        price = _num(inv_units)                 # 1 BASE = price QUOTE
        quote = inv_quote or tx_quote
        return {
            "pair": _normalize_pair(None, base, quote),
            "side": "BUY",
            "price": price,
            "qty": _num(qty),
            "fee": 0.0,
            "fee_asset": None,
            "time": None,
        }
    elif qty and base and dir_units and (dir_quote or tx_quote):
        units = _num(dir_units)                 # 1 QUOTE = units BASE  -> price = 1/units
        price = (1.0 / units) if units else None
        quote = dir_quote or tx_quote
        return {
            "pair": _normalize_pair(None, base, quote),
            "side": "BUY",
            "price": price,
            "qty": _num(qty),
            "fee": 0.0,
            "fee_asset": None,
            "time": None,
        }

    # ---------- 2) Generic single filled (เช่น Easy Buy/Sell Details) ----------
    pair = _first_match(PAT.get("pair_patterns", []), text, "pair")
    base_only = _first_match(PAT.get("pair_patterns", []), text, "base")
    side_raw = _first_match(PAT.get("side_patterns", []), text, "side")
    price = _first_match(PAT.get("price_patterns", []), text, "price")
    qty = qty or _first_match(PAT.get("qty_patterns", []), text, "qty")
    fee = _first_match(PAT.get("fee_patterns", []), text, "fee")
    fee_asset = _first_match(PAT.get("fee_patterns", []), text, "fee_asset")
    ttime = _first_match(PAT.get("time_patterns", []), text, "time")

    # Total (QUOTE) — จำนวนเงินรวมฝั่ง QUOTE และสกุล
    total_amt = _first_match(PAT.get("total_patterns", []), text, "total")
    total_q = _first_match(PAT.get("total_quote_patterns", []), text, "quote")

    # เผื่อบางสลิปไม่มี price_patterns แต่มี Inverse/Direct
    if price is None:
        inv_units = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "units")
        dir_units = _first_match(PAT.get("convert_direct_price_patterns", []), text, "units")
        if inv_units:
            price = _num(inv_units)
        elif dir_units:
            u = _num(dir_units)
            price = (1.0 / u) if u else None

    # ประกอบ pair ถ้ายังไม่ครบ
    if (pair is None or "/" not in pair) and base_only:
        qsym = total_q or _first_match(PAT.get("convert_direct_price_patterns", []), text, "quote") \
               or _first_match(PAT.get("convert_inverse_price_patterns", []), text, "quote")
        if qsym:
            pair = f"{base_only}/{qsym}"

    # จัด side
    side = None
    if side_raw:
        s = side_raw.strip().upper()
        if s in ("BUY", "ซื้อ"):
            side = "BUY"
        elif s in ("SELL", "ขาย"):
            side = "SELL"

    trade = {
        "pair": _normalize_pair(pair, base_only),
        "side": side,
        "price": _num(price),
        "qty": _num(qty),
        "fee": _num(fee),
        "fee_asset": (fee_asset or "").upper() or None,
        "time": ttime,
        "quote_amount": _num(total_amt),
        "quote_asset": (total_q or "").upper() or None,
    }
    return trade


# ---------------- Wallet parser ----------------
def parse_wallet_from_text(text: str):
    # ต้องมีลายเซ็นหน้าวอลเล็ตก่อน
    if not _first_match(PAT.get("wallet_detector_patterns", []), text, "xx"):
        return None

    assets = []
    for line in (l.strip() for l in text.splitlines()):
        for pat in PAT.get("wallet_row_patterns", []):
            m = re.search(pat, line)
            if not m:
                continue
            sym = m.group("asset")
            qty = _num(m.group("qty"))
            usd = _num(m.groupdict().get("usd"))
            # กันชื่อที่ไม่ใช่เหรียญจริง และ qty ต้องไม่ None
            if sym and sym.isupper() and qty is not None:
                assets.append({"asset": sym, "qty": qty, "usd": usd})
                break

    return {"type": "wallet", "assets": assets} if len(assets) > 0 else None


def parse_from_text(text: str):
    # 1) ลองเป็น "trade" ก่อน
    trade = parse_trade_from_text(text)
    if trade:
        return {"kind": "trade", "data": trade}

    # 2) ถ้าไม่ใช่ trade → ลองเป็น "wallet"
    wallet = parse_wallet_from_text(text)
    if wallet:
        return {"kind": "wallet", "data": wallet}

    # 3) ไม่เข้าเงื่อนไขใดเลย
    return None