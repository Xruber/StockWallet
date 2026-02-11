import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

from config import BOT_TOKEN, ADMIN_ID, MONGO_URI
from database import get_user_data

from handlers_wallet import (
    wallet_command, tokens_command, view_token_chart, ask_trade_amount, execute_trade,
    admin_payment_handler, start_deposit, select_deposit_amount, show_qr_code, 
    ask_utr, receive_utr, start_withdraw, select_withdraw_method, ask_withdraw_details, 
    process_withdrawal, DEP_AMOUNT, DEP_METHOD, DEP_UTR, WD_AMOUNT, WD_METHOD, WD_DETAILS, TRADE_AMOUNT,
    token_rig_command, token_roi_list_command
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_command(update: Update, context):
    uid = update.effective_user.id
    get_user_data(uid) # Initialize user in database if new
    
    msg = (
        f"🏦 **CRYPTO EXCHANGE BOT**\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👋 Welcome, {update.effective_user.first_name}!\n"
        f"🆔 ID: `{uid}`\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Manage your portfolio, deposit funds, and trade tokens."
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 My Wallet", callback_data="wallet_main")],
        [InlineKeyboardButton("📈 Token Market", callback_data="wallet_tokens")]
    ])
    
    if update.callback_query:
        if update.callback_query.message.photo:
            await update.callback_query.message.delete()
            await context.bot.send_message(uid, msg, reply_markup=kb, parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

async def back_home_handler(update: Update, context):
    await start_command(update, context)
    return ConversationHandler.END

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("token_rig", token_rig_command))
    app.add_handler(CommandHandler("token_roi_list", token_roi_list_command))
    
    app.add_handler(CallbackQueryHandler(back_home_handler, pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(admin_payment_handler, pattern="^adm_(dep|wd)_"))

    # TRADING CONVERSATION (Buy/Sell Amount)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_trade_amount, pattern="^ask_(buy|sell)_")],
        states={TRADE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, execute_trade)]},
        fallbacks=[CallbackQueryHandler(view_token_chart, pattern="^view_chart_"), CallbackQueryHandler(wallet_command, pattern="^wallet_main$")],
        per_user=True
    ))

    # DEPOSIT CONVERSATION
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_deposit, pattern="^start_deposit$")],
        states={
            DEP_AMOUNT: [CallbackQueryHandler(select_deposit_amount, pattern="^dep_amt_")],
            DEP_METHOD: [CallbackQueryHandler(show_qr_code, pattern="^dep_method_")],
            DEP_UTR: [CallbackQueryHandler(ask_utr, pattern="^dep_paid$"), MessageHandler(filters.TEXT & ~filters.COMMAND, receive_utr)]
        },
        fallbacks=[CallbackQueryHandler(wallet_command, pattern="^wallet_main$")],
        per_user=True
    ))

    # WITHDRAW CONVERSATION
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_withdraw, pattern="^start_withdraw$")],
        states={
            WD_AMOUNT: [CallbackQueryHandler(select_withdraw_method, pattern="^wd_amt_")],
            WD_METHOD: [CallbackQueryHandler(ask_withdraw_details, pattern="^wd_method_")],
            WD_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_withdrawal)]
        },
        fallbacks=[CallbackQueryHandler(wallet_command, pattern="^wallet_main$")],
        per_user=True
    ))

    # STANDARD CALLBACKS
    app.add_handler(CallbackQueryHandler(wallet_command, pattern="^wallet_main$"))
    app.add_handler(CallbackQueryHandler(tokens_command, pattern="^wallet_tokens$"))
    app.add_handler(CallbackQueryHandler(view_token_chart, pattern="^view_chart_"))
    
    print("✅ PURE WALLET BOT ONLINE (Isolated from Wingo)")
    app.run_polling()

if __name__ == "__main__":
    main()
