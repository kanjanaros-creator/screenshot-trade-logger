from storage import TradeStorage
from typing import Dict, Any

class PnLEngine:
    def __init__(self, storage: TradeStorage):
        self.storage = storage

    def record_trade(self, trade: Dict[str, Any]) -> str:
        required = ["pair","side","price","qty"]
        missing = [k for k in required if not trade.get(k)]
        if missing:
            return f"ข้อมูลไม่พอ: {', '.join(missing)} — โปรดพิมพ์แก้ไขเป็น JSON แล้วพิมพ์ 'ok' อีกครั้ง"

        pair = trade["pair"]
        side = trade["side"]
        price = float(trade["price"])
        qty = float(trade["qty"])
        fee = float(trade.get("fee") or 0.0)

        self.storage.record_trade(trade)

        pos = self.storage.get_position(pair)
        position_qty = float(pos.get("position_qty") or 0.0)
        avg_cost = float(pos.get("avg_cost") or 0.0)

        if side == "BUY":
            new_qty = position_qty + qty
            new_avg = ((position_qty * avg_cost) + (qty * price)) / new_qty if new_qty > 0 else price
            self.storage.upsert_position(pair, new_qty, new_avg)
            return f"บันทึก BUY {pair} qty={qty} ที่ {price} สำเร็จ ✅\nposition: qty={new_qty:.6f}, avg_cost={new_avg:.6f}"

        elif side == "SELL":
            sell_qty = min(qty, position_qty)
            realized = (price - avg_cost) * sell_qty - fee
            self.storage.record_realized(pair, sell_qty, avg_cost, price, fee, realized, trade.get("src_image_id"))
            new_qty = position_qty - sell_qty
            new_avg = avg_cost if new_qty > 0 else 0.0
            self.storage.upsert_position(pair, new_qty, new_avg)
            extra = ""
            if qty > position_qty:
                extra = f"\n*หมายเหตุ*: ปริมาณขาย ({qty}) > position ({position_qty}), ระบบตัดขายเท่าที่มีคือ {sell_qty}"
            return f"บันทึก SELL {pair} qty={sell_qty} ที่ {price} สำเร็จ ✅\nrealized P&L = {realized:.6f}{extra}\nposition: qty={new_qty:.6f}, avg_cost={new_avg:.6f}"

        return "Side ไม่ถูกต้อง (ควรเป็น BUY/SELL)"
