import re
import yaml
from typing import Dict, Any, Optional

# โหลดแพทเทิร์น/คอนฟิก
with open("parser_patterns.yaml", "r", encoding="utf-8") as f:
    PAT = yaml.safe_load(f) or {}

with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f) or {}

# ---------------- helpers ----------------

def _first_match(patterns, text: str, group_name: str) -> Optional[str]:
    """วน regex หลายอันแล้วคืน group ที่เจอแรกสุด"""
    for pat in patterns or []:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m and group_name in (m.groupdict() or {}):
            return m.group(group_name)
    return None


def guess_exchange(text: str) -> str:
    t = text.lower()
    for ex, keys in (CFG.get("exchange_keywords") or {}).items():
        if any((k or "").lower() in t for k in keys or []):
            return ex
    return "unknown"


def _normalize_pair(text_pair: Optional[str],
                    base: Optional[str] = None,
                    quote: Optional[str] = None) -> Optional[str]:
    """แปลงให้เป็นรูป BASE/QUOTE ให้เรียบร้อย"""
    if text_pair:
        up = text_pair.upper().replace(" ", "")
        return up if "/" in up else (f"{up}/{(quote or 'USDT').upper()}")
    if base and quote:
        return f"{base.upper()}/{quote.upper()}"
    if base:
        return f"{base.upper()}/USDT"
    return None


def _num(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None

# ---------------- parsers ----------------

def parse_trade_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    แยกข้อมูล 'trade' จากข้อความ OCR
    คืน None ถ้าไม่ใช่ trade (เพื่อให้ไปลอง parse wallet ต่อ)
    """

    # 1) เคส Binance Convert "Successful"
    qty        = _first_match(PAT.get("convert_receive_patterns", []), text, "qty")
    base       = _first_match(PAT.get("convert_receive_patterns", []), text, "asset")

    inv_p      = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "price")
    inv_q      = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "quote")

    dir_units  = _first_match(PAT.get("convert_direct_price_patterns", []), text, "units")
    dir_quote  = _first_match(PAT.get("convert_direct_price_patterns", []), text, "quote")

    tx_quote   = _first_match(PAT.get("convert_tx_amount_patterns", []), text, "quote")
    from_amt   = _first_match(PAT.get("convert_tx_amount_patterns", []), text, "amount")
    from_quote = _first_match(PAT.get("convert_tx_amount_patterns", []), text, "quote")

    # inverse price (แอปโชว์ "1 BASE = price QUOTE")
    if qty and base and inv_p and (inv_q or tx_quote):
        price = _num(inv_p)
        quote = inv_q or tx_quote
        return {
            "pair": _normalize_pair(None, base, quote),
            "side": "BUY",
            "price": price,
            "qty": _num(qty),
            "fee": 0.0,
            "fee_asset": None,
            "time": None,
            # ใช้เป็นยอดที่จ่ายไป/ได้รับฝั่ง QUOTE
            "quote_amount": _num(from_amt or None),
            "quote_asset": (from_quote or tx_quote),
        }

    # direct price (แอปโชว์ "1 QUOTE = units BASE")
    if qty and base and dir_units and (dir_quote or tx_quote):
        units = _num(dir_units)
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
            "quote_amount": _num(from_amt or None),
            "quote_asset": (from_quote or tx_quote),
        }

    # 2) Generic single filled (เช่น การเทรดคู่ SOL/BTC แบบปกติ)
    pair       = _first_match(PAT.get("pair_patterns", []),  text, "pair")
    base_only  = _first_match(PAT.get("pair_patterns", []),  text, "base")
    side_raw   = _first_match(PAT.get("side_patterns", []),  text, "side")
    price      = _first_match(PAT.get("price_patterns", []), text, "price")
    qty        = qty or _first_match(PAT.get("qty_patterns", []),   text, "qty")
    fee        = _first_match(PAT.get("fee_patterns", []),    text, "fee")
    fee_asset  = _first_match(PAT.get("fee_patterns", []),    text, "asset")
    ttime      = _first_match(PAT.get("time_patterns", []),   text, "time")

    # Total (QUOTE)
    total_amt = _first_match(PAT.get("total_patterns", []), text, "total")
    total_q   = _first_match(PAT.get("total_quote_patterns", []), text, "quote")

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
        "quote_asset":  (total_q or "").upper() or None,
    }

    # ถ้าไม่มีข้อมูลหลัก ๆ เลย ให้คืน None เพื่อไปลอง parse wallet
    core = any([
        trade["pair"] is not None,
        trade["price"] is not None,
        trade["qty"] is not None,
        trade["side"] is not None,
    ])
    return trade if core else None


def parse_wallet_from_text(text: str) -> Optional[Dict[str, Any]]:
    """แยกหน้า wallet snapshot (รายชื่อเหรียญในพอร์ต)"""
    # ต้องมี "ตัวบ่งชี้" ว่าเป็นหน้า wallet ก่อน
    has_wallet = any(re.search(p, text, flags=re.IGNORECASE)
                     for p in (PAT.get("wallet_detector_patterns") or []))
    if not has_wallet:
        return None

    assets = []
    for line in (l.strip() for l in text.splitlines() if l.strip()):
        for pat in PAT.get("wallet_row_patterns", []) or []:
            m = re.search(pat, line, flags=re.IGNORECASE)
            if not m:
                continue
            sym = m.group("asset")
            qty = _num(m.group("qty")) if "qty" in m.groupdict() else None
            usd = _num(m.group("usd")) if "usd" in m.groupdict() else None
            if sym and sym.isupper() and qty is not None:
                assets.append({"asset": sym, "qty": qty, "usd": usd})
                break

    return {"type": "wallet", "assets": assets} if assets else None


def parse_from_text(text: str) -> Optional[Dict[str, Any]]:
    """ตัว dispatch หลัก: ลอง trade ก่อน ถ้าไม่ใช่ค่อยลอง wallet"""
    trade = parse_trade_from_text(text)
    if trade:
        return {"kind": "trade", "data": trade}

    wallet = parse_wallet_from_text(text)
    if wallet:
        return {"kind": "wallet", "data": wallet}

    return None