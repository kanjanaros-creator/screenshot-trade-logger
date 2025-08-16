import re
import yaml
from typing import Dict, Any

with open("parser_patterns.yaml", "r", encoding="utf-8") as f:
    PAT = yaml.safe_load(f)

with open("config.yaml", "r", encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

def _first_match(patterns, text, group_name):
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if m and group_name in m.groupdict() and m.group(group_name):
            return m.group(group_name)
    return None

def guess_exchange(text: str) -> str:
    t = text.lower()
    for ex, keys in (CFG.get("exchange_keywords") or {}).items():
        if any(k.lower() in t for k in keys):
            return ex
    return "unknown"

def _normalize_pair(text_pair: str, base: str = None, quote: str = None) -> str:
    if text_pair:
        up = text_pair.upper().replace(" ", "")
        if "/" not in up and quote:
            return f"{up}/{quote.upper()}"
        return up
    if base and quote:
        return f"{base.upper()}/{quote.upper()}"
    if base:
        return f"{base.upper()}/USDT"
    return None

def _num(x):
    if x is None: return None
    return float(str(x).replace(",", ""))

def parse_trade_from_text(text: str) -> Dict[str, Any]:
    # 1) Binance Convert "Successful"
    qty = _first_match(PAT.get("convert_receive_patterns", []), text, "qty")
    base = _first_match(PAT.get("convert_receive_patterns", []), text, "base")
    inv_p = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "price")
    inv_q = _first_match(PAT.get("convert_inverse_price_patterns", []), text, "quote")
    from_amount = _first_match(PAT.get("convert_from_amount_patterns", []), text, "amount")
    from_quote  = _first_match(PAT.get("convert_from_amount_patterns", []), text, "quote")
    dir_units = _first_match(PAT.get("convert_direct_price_patterns", []), text, "units")
    dir_quote = _first_match(PAT.get("convert_direct_price_patterns", []), text, "quote")
    tx_quote = _first_match(PAT.get("convert_tx_amount_patterns", []), text, "quote")

    if qty and base and (inv_p and (inv_q or tx_quote)):
        price = _num(inv_p)  # 1 BASE = price QUOTE
        quote = inv_q or tx_quote
        return {
    "pair": _normalize_pair(None, base, quote),
    "side": "BUY",
    "price": price,
    "qty": _num(qty),
    "quote_amount": _num(from_amount or None),  # ✅ จำนวน BTC ที่ใช้
    "quote_asset":  (from_quote or tx_quote),   # ✅ สกุลที่ใช้ (เช่น BTC)
    "fee": 0.0,
    "fee_asset": None,
    "time": None,
        }
    elif qty and base and dir_units and (dir_quote or tx_quote):
        units = _num(dir_units)
        price = (1.0 / units) if units else None
        quote = dir_quote or tx_quote
        return {
    "pair": _normalize_pair(None, base, quote),
    "side": "BUY",
    "price": price,
    "qty": _num(qty),
    "quote_amount": _num(from_amount or None),
    "quote_asset":  (from_quote or dir_quote or tx_quote),
    "fee": 0.0,
    "fee_asset": None,
    "time": None,
         }

    # 2) Generic single filled
    pair = _first_match(PAT.get("pair_patterns", []), text, "pair")
    base_only = _first_match(PAT.get("pair_patterns", []), text, "base")
    side_raw = _first_match(PAT.get("side_patterns", []), text, "side")
    price = _first_match(PAT.get("price_patterns", []), text, "price")
    qty = qty or _first_match(PAT.get("qty_patterns", []), text, "qty")
    fee = _first_match(PAT.get("fee_patterns", []), text, "fee")
    fee_asset = _first_match(PAT.get("fee_patterns", []), text, "fee_asset")
    ttime = _first_match(PAT.get("time_patterns", []), text, "time")
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
    }
    return trade

import re  # แนะนำให้อยู่บนสุดของไฟล์

def parse_wallet_from_text(text: str):
    # ถ้าไม่มีกลายเซ็นหน้า wallet ก็เลิก
    if not _first_match(PAT.get("wallet_detector_patterns", []), text):
        return None

    import re
    assets = []
    for line in (l.strip() for l in text.splitlines()):
        for pat in PAT.get("wallet_row_patterns", []):
            m = re.search(pat, line)
            if m:
                sym = m.group('asset')
                qty = _num(m.group('qty'))
                usd = _num(m.groupdict().get('usd'))
                # กันชื่อที่ไม่ใช่เหรียญจริง และ qty ต้องไม่ None
                if sym and sym.isupper() and qty is not None:
                    assets.append({"asset": sym, "qty": qty, "usd": usd})
                break
    return {"type": "wallet", "assets": assets} if len(assets) > 0 else None


def parse_from_text(text: str):
    # 1) พยายามตีความเป็น "trade" ก่อน
    trade = parse_trade_from_text(text)
    if trade:
        return {"kind": "trade", "data": trade}

    # 2) ถ้าไม่ใช่ trade ให้ลองตีความเป็น "wallet"
    wallet = parse_wallet_from_text(text)
    if wallet:
        return {"kind": "wallet", "data": wallet}

    # 3) ไม่เข้าเงื่อนไขใดเลย
    return None
