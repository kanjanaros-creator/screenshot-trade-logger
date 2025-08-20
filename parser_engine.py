import re
import yaml
from typing import Dict, Any

# โหลด patterns และ config
with open("parser_patterns.yaml", "r", encoding="utf-8") as f:
    PAT = yaml.safe_load(f)

try:
    with open("config.yaml", "r", encoding="utf-8") as f:
        CFG = yaml.safe_load(f)
except FileNotFoundError:
    CFG = {}

def _first_match(patterns, text, group_name):
    """คืนค่ากลุ่มที่ต้องการจากลิสต์เรกซ์เพรสชันแรกที่เจอ"""
    for pat in (patterns or []):
        m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
        if m and group_name in (m.groupdict() or {}):
            g = m.group(group_name)
            if g is not None and g != "":
                return str(g).strip()
    return None

def guess_exchange(text: str) -> str:
    t = text.lower()
    for ex, keys in (CFG.get("exchange_keywords") or {}).items():
        if any(k.lower() in t for k in keys):
            return ex
    return "unknown"

def _normalize_pair(text_pair: str, base_only: str = None, quote: str = None):
    if text_pair:
        up = text_pair.upper().replace(" ", "")
        if "/" not in up and quote:
            return f"{up}/{quote.upper()}"
        return up
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

# ---------------- Trade parser ----------------

def parse_trade_from_text(text: str) -> Dict[str, Any] | None:
    """พยายามตีความเป็น “trade” ก่อน ถ้าได้จะคืน dict ของ trade"""

    # ----- 1) Binance Convert slips -----
    qty       = _first_match(PAT.get("convert_receive_patterns", []), text, "qty")
    base      = _first_match(PAT.get("convert_receive_patterns", []), text, "base")

    inv_p     = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "price")
    inv_q     = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "quote")

    dir_units = _first_match(PAT.get("convert_direct_price_patterns", []), text, "units")  # units BASE per 1 QUOTE
    dir_quote = _first_match(PAT.get("convert_direct_price_patterns", []), text, "quote")

    tx_quote  = _first_match(PAT.get("convert_tx_amount_patterns", []), text, "quote")
    from_amt  = _first_match(PAT.get("convert_from_amount_patterns", []), text, "amount")
    from_q    = _first_match(PAT.get("convert_from_amount_patterns", []), text, "quote")

    ttime     = _first_match(PAT.get("time_patterns", []), text, "time")

    # Inverse line: "Inverse Price 1 CRV = 0.00000741 BTC"
    if qty and base and (inv_p and (inv_q or tx_quote)):
        price = _num(inv_p)                          # 1 BASE = price QUOTE
        quote = inv_q or tx_quote
        return {
            "pair": _normalize_pair(None, base, quote),
            "side": "BUY",
            "price": price,
            "qty": _num(qty),
            "fee": 0.0,
            "fee_asset": None,
            "time": ttime,
            "quote_amount": _num(from_amt),
            "quote_asset": (from_q or tx_quote),
        }

    # Direct line: "Price 1 BTC = 134910.5 CRV"
    if qty and base and dir_units and (dir_quote or tx_quote):
        units = _num(dir_units)
        price = (1.0 / units) if units else None     # price (QUOTE per 1 BASE)
        quote = dir_quote or tx_quote
        return {
            "pair": _normalize_pair(None, base, quote),
            "side": "BUY",
            "price": price,
            "qty": _num(qty),
            "fee": 0.0,
            "fee_asset": None,
            "time": ttime,
            "quote_amount": _num(from_amt),
            "quote_asset": (from_q or tx_quote),
        }

    # ----- 2) Generic single filled slips (เช่น SOL/BTC Spot) -----
    pair       = _first_match(PAT.get("pair_patterns", []), text, "pair")
    base_only  = _first_match(PAT.get("pair_patterns", []), text, "base")
    side_raw   = _first_match(PAT.get("side_patterns", []), text, "side")
    price      = _first_match(PAT.get("price_patterns", []), text, "price")
    qty_val    = _first_match(PAT.get("qty_patterns", []), text, "qty")
    fee        = _first_match(PAT.get("fee_patterns", []), text, "fee")
    fee_asset  = _first_match(PAT.get("fee_patterns", []), text, "fee_asset")
    ttime      = ttime or _first_match(PAT.get("time_patterns", []), text, "time")

    total_amt  = _first_match(PAT.get("total_patterns", []), text, "total")
    total_q    = _first_match(PAT.get("total_quote_patterns", []), text, "quote")

    side = None
    if side_raw:
        s = side_raw.strip().upper()
        if s in ("BUY", "ซื้อ"):
            side = "BUY"
        elif s in ("SELL", "ขาย"):
            side = "SELL"

    trade = {
        "pair": _normalize_pair(pair, base_only, total_q),
        "side": side,
        "price": _num(price),
        "qty": _num(qty_val),
        "fee": _num(fee),
        "fee_asset": (fee_asset or "").upper() or None,
        "time": ttime,
        # สรุปยอดฝั่ง QUOTE (เช่น Total (BTC) ...)
        "quote_amount": _num(total_amt),
        "quote_asset": (total_q or "").upper() or None,
    }
    return trade

# ---------------- Wallet parser ----------------

def parse_wallet_from_text(text: str):
    """อ่านหน้า Wallet list ถ้าพบอย่างน้อย 1 บรรทัด ให้คืนรายการ"""
    assets = []
    for line in [l.strip() for l in text.splitlines()]:
        for pat in (PAT.get("wallet_row_patterns", []) or []):
            m = re.search(pat, line, flags=re.IGNORECASE)
            if m:
                sym = (m.group("asset") or "").upper()
                qty = _num(m.group("qty"))
                usd = _num((m.groupdict() or {}).get("usd"))
                if sym and sym.isupper() and qty is not None:
                    assets.append({"asset": sym, "qty": qty, "usd": usd})
                break
    if assets:
        return {"type": "wallet", "assets": assets}
    return None

# ---------------- Entry point ----------------

def parse_from_text(text: str):
    trade = parse_trade_from_text(text)
    if trade:
        return {"kind": "trade", "data": trade}
    wallet = parse_wallet_from_text(text)
    if wallet:
        return {"kind": "wallet", "data": wallet}
    return None