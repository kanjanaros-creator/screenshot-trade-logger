import os, io, json, logging
from datetime import datetime, timezone
from typing import Dict, Any

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from ocr_engine import extract_text_from_image
from parser_engine import parse_from_text, guess_exchange
from storage import TradeStorage
from pnl import PnLEngine
from utils import parse_bool
from decimal import Decimal, getcontext
getcontext().prec = 18

def fmt(x):
    if x is None:
        return "-"
    s = format(Decimal(str(x)), "f").rstrip("0").rstrip(".")
    return s if s else "0"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tradebot")

AUTO_ACCEPT = parse_bool(os.getenv("AUTO_ACCEPT", "false"))

storage = TradeStorage()
pnl = PnLEngine(storage)

WELCOME_TH = (
    "สวัสดีค่ะ! ส่งรูปแคปตอนเทรดมาได้เลย เดี๋ยวฉันดึงข้อมูลและบันทึกให้\n"
    "คำสั่ง:\n"
    "• /auto_on – บันทึกอัตโนมัติ ไม่ต้องยืนยัน\n"
    "• /auto_off – ปิดบันทึกอัตโนมัติ\n"
    "• /status – ดูสรุปสั้น ๆ\n"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME_TH)

async def auto_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global AUTO_ACCEPT
    AUTO_ACCEPT = True
    os.environ["AUTO_ACCEPT"] = "true"
    await update.message.reply_text("เปิดโหมดบันทึกอัตโนมัติแล้ว ✅")

async def auto_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global AUTO_ACCEPT
    AUTO_ACCEPT = False
    os.environ["AUTO_ACCEPT"] = "false"
    await update.message.reply_text("ปิดโหมดบันทึกอัตโนมัติแล้ว ✅")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pos = storage.get_all_positions()
    if not pos:
        await update.message.reply_text("ยังไม่มี position ในระบบค่ะ")
        return
    lines = ["สถานะคงเหลือ (ล่าสุด):"]
    for p in pos:
        try:
            qty = float(p.get("position_qty"))
            avg = float(p.get("avg_cost"))
        except Exception:
            qty = float(p.get("position_qty", 0) or 0)
            avg = float(p.get("avg_cost", 0) or 0)
        lines.append(f"- {p.get('pair')}: qty={qty:.6f}, avg_cost={avg:.6f}")
    await update.message.reply_text("\n".join(lines))

def _format_preview(trade):
    kv = []
    if trade.get("exchange"):
        kv.append(f"exchange: {trade['exchange']}")
    if trade.get("pair"):
        kv.append(f"pair: {trade['pair']}")
    if trade.get("side"):
        kv.append(f"side: {trade['side']}")
    if trade.get("price") is not None:
        kv.append(f"price: {fmt(trade['price'])}")
    if trade.get("qty") is not None:
        kv.append(f"qty: {fmt(trade['qty'])}")
    if trade.get("fee") is not None:
        kv.append(f"fee: {fmt(trade['fee'])}")
    if trade.get("quote_amount"):
        qa = fmt(trade['quote_amount'])
        qas = trade.get("quote_asset") or ""
        kv.append(f"spent: {qa} {qas}")
    if trade.get("time"):
        kv.append(f"time: {trade['time']}")
    return "พบข้อมูลต่อไปนี้ค่ะ:\n" + "\n".join(kv)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photos = update.message.photo
    if not photos:
        await update.message.reply_text("ไม่พบรูปภาพค่ะ")
        return
    photo = photos[-1]
    bio = await photo.get_file()
    img_bytes = await bio.download_as_bytearray()
    text = extract_text_from_image(io.BytesIO(img_bytes))
    ex = guess_exchange(text)
    parsed = parse_from_text(text)
    logger.info("parsed=%s", parsed)
    # ถ้าอ่านไม่ออกเลย
if not parsed:
    await update.message.reply_text("ยังอ่านข้อมูลจากรูปนี้ไม่ออก ลองถ่ายให้ชัดขึ้นหรือส่งรูปหน้าอื่นนะคะ")
    return

# ถ้าเป็นหน้า Wallet → สรุปรายการแล้วรอพิมพ์ ok เพื่อบันทึก
if parsed["kind"] == "wallet":
    try:
        assets = parsed["data"]["assets"]
        lines = []
        for a in assets[:8]:
            qty = a.get("qty")
            usd = a.get("usd")           # ใช้ .get ป้องกัน KeyError
            line = f"{a.get('asset','?')}: {fmt(qty)}"
            if usd is not None:
                line += f" (${fmt(usd)})"
            lines.append(line)

        msg = "พบบัญชีพอร์ตค่ะ:\n" + "\n".join(lines)
        if len(assets) > 8:
            msg += f"\n… และอีก {len(assets)-8} รายการ"
        msg += "\n\nพิมพ์ 'ok' เพื่อบันทึกเป็นสแน็ปช็อตล่าสุด"

        context.user_data["pending_wallet"] = assets
        await update.message.reply_text(msg)
    except Exception as e:
        logger.exception("wallet preview failed")
        await update.message.reply_text(f"มีข้อผิดพลาดตอนพรีวิวพอร์ต: {e}")
    return
# ถ้าเป็น trade → ตั้งค่า trade แล้วปล่อยให้ไปเข้าบล็อกพรีวิวเดิมด้านล่าง
trade = parsed["data"]
trade["exchange"] = trade.get("exchange") or ex
trade["src_image_id"] = photo.file_unique_id
trade["ts_iso"] = datetime.now(timezone.utc).isoformat()

    if not AUTO_ACCEPT:
        preview = _format_preview(trade)
        preview += "\n\nพิมพ์ 'ok' เพื่อยืนยัน หรือส่งข้อความแก้ไขเป็น JSON (เช่น {\"price\": 0.123})"
        await update.message.reply_text(preview)
        context.user_data["pending_trade"] = trade
    else:
        result_msg = pnl.record_trade(trade)
        await update.message.reply_text(result_msg)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    pending_trade = context.user_data.get("pending_trade")
    pending_wallet = context.user_data.get("pending_wallet")

    # 1) ยืนยันบันทึก "พอร์ต" (จากหน้า Wallet)
    if pending_wallet and txt.lower() in ("ok", "โอเค", "ตกลง", "yes", "y"):
        try:
            pnl.storage.record_snapshot(pending_wallet)  # ต้องมี record_snapshot ใน storage.py
        except Exception as e:
            await update.message.reply_text(f"บันทึกพอร์ตไม่สำเร็จ: {e}")
        else:
            context.user_data["pending_wallet"] = None
            await update.message.reply_text("บันทึกพอร์ตแล้วค่า ✅")
        return

    # 2) ยืนยันบันทึก "trade"
    if pending_trade:
        if txt.lower() in ("ok", "โอเค", "ตกลง", "yes", "y"):
            result_msg = pnl.record_trade(pending_trade)
            context.user_data["pending_trade"] = None
            await update.message.reply_text(result_msg)
            return
        try:
            patch = json.loads(txt)       # รองรับพิมพ์แก้ไขเป็น JSON
            pending_trade.update(patch)
            result_msg = pnl.record_trade(pending_trade)
            context.user_data["pending_trade"] = None
            await update.message.reply_text(result_msg)
        except Exception:
            await update.message.reply_text("ไม่เข้าใจข้อความที่แก้ไขค่ะ (ต้องเป็น JSON)")

        return

    # ไม่มีอะไร pending
    await update.message.reply_text("ส่งรูปแคปหน้าการเทรดหรือหน้า Wallet มาได้เลยค่ะ")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN ไม่ถูกตั้งค่า")
        return
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auto_on", auto_on))
    app.add_handler(CommandHandler("auto_off", auto_off))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    logger.info("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
