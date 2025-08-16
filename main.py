import os, io, json, logging
from datetime import datetime, timezone
from typing import Dict, Any

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from ocr_engine import extract_text_from_image
from parser_engine import parse_trade_from_text, guess_exchange
from storage import TradeStorage
from pnl import PnLEngine
from utils import parse_bool

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

def _format_preview(trade: Dict[str, Any]) -> str:
    kv = []
    for k in ["exchange","pair","side","price","qty","fee","fee_asset","time"]:
        if k in trade and trade[k] is not None:
            kv.append(f"{k}: {trade[k]}")
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
    trade = parse_trade_from_text(text)
    trade["exchange"] = ex
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (update.message.text or "").strip()
    pending = context.user_data.get("pending_trade")
    if pending:
        if txt.lower() in ("ok","โอเค","ตกลง","yes","y"):
            result_msg = pnl.record_trade(pending)
            context.user_data["pending_trade"] = None
            await update.message.reply_text(result_msg)
            return
        try:
            patch = json.loads(txt)
            pending.update(patch)
            result_msg = pnl.record_trade(pending)
            context.user_data["pending_trade"] = None
            await update.message.reply_text(result_msg)
        except Exception:
            await update.message.reply_text("ไม่เข้าใจข้อความค่ะ ถ้าต้องการยืนยันให้พิมพ์ 'ok' หรือส่งแก้ไขเป็น JSON")
    else:
        await update.message.reply_text("ส่งรูปแคปหน้าจอการเทรดมาได้เลยค่ะ (หรือใช้ /start)")

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