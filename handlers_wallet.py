import io
import time
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import (
    get_user_wallet, get_all_tokens, update_wallet_balance, 
    trade_token, create_transaction, get_user_transactions, 
    update_transaction_status, get_transaction, get_user_data,
    update_token_price, users_collection, get_token_details,
    record_first_deposit, get_daily_stats, generate_gift_code, 
    redeem_gift_code, get_current_token_stats, get_token_roi_list,
    get_platform_profit_by_token
)
from config import ADMIN_ID, PAYMENT_IMAGE_URL

try:
    import matplotlib
    matplotlib.use('Agg') 
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("⚠️ Matplotlib not found. Charts disabled.")

DEP_AMOUNT, DEP_METHOD, DEP_UTR = range(10, 13)
WD_AMOUNT, WD_METHOD, WD_DETAILS = range(20, 23)
TRADE_AMOUNT = 30 

def generate_chart_image(symbol, history):
    if not HAS_MATPLOTLIB: return None
    try:
        fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
        color = '#00ff00' if len(history) > 1 and history[-1] >= history[0] else '#ff0000'
        ax.plot(history, marker='o', linestyle='-', color=color, linewidth=2, markersize=4)
        ax.set_title(f"{symbol} Price History")
        ax.set_ylabel("Price (INR)")
        ax.grid(True, linestyle='--', alpha=0.3)
        
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        print(f"Chart Error: {e}")
        return None

# ==========================================
# 1. MAIN WALLET MENU
# ==========================================
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    wallet = get_user_wallet(uid)
    bal = wallet['balance']
    
    tokens = get_all_tokens()
    assets_val = 0
    holdings = wallet.get('holdings', {})
    holdings_txt = ""
    
    for t in tokens:
        sym = t['symbol']
        qty = holdings.get(sym, 0)
        if qty > 0:
            val = qty * t['price']
            assets_val += val
            assets_val += val
            holdings_txt += f"🔹 **{t['name']}:** {qty} (≈₹{int(val)})\n"

    txs = get_user_transactions(uid, limit=3)
    pending_txt = ""
    for tx in txs:
        if tx['status'] == 'pending':
            icon = "📥" if tx['type'] == 'deposit' else "📤"
            pending_txt += f"{icon} **{tx['type'].title()}:** ₹{tx['amount']} (Pending)\n"

    msg = (
        f"👛 **YOUR WALLET**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Fiat Balance: **₹{bal:.2f}**\n"
        f"💎 Asset Value: **₹{assets_val:.2f}**\n"
        f"📊 **Net Worth: ₹{bal + assets_val:.2f}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"**⏳ PENDING:**\n{pending_txt if pending_txt else 'No pending transactions.'}\n"
        f"━━━━━━━━━━━━━━\n"
        f"**📂 PORTFOLIO:**\n{holdings_txt if holdings_txt else 'No tokens owned.'}"
    )
    
    kb = [
        [InlineKeyboardButton("➕ Deposit", callback_data="start_deposit"), InlineKeyboardButton("➖ Withdraw", callback_data="start_withdraw")],
        [InlineKeyboardButton("📈 Token Market", callback_data="wallet_tokens")],
        [InlineKeyboardButton("🔙 Home", callback_data="back_home")]
    ]
    
    if update.callback_query:
        if update.callback_query.message.photo:
            await update.callback_query.message.delete()
            await context.bot.send_message(uid, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ==========================================
# 2. TOKEN MARKET & CHARTS
# ==========================================
async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tokens = get_all_tokens()
    
    msg = "📈 **TOKEN MARKET**\nSelect a token to view Chart & Trade:\n━━━━━━━━━━━━━━\n"
    kb = []
    for t in tokens:
        kb.append([InlineKeyboardButton(f"{t['name']} ({t['symbol']}) - ₹{t['price']}", callback_data=f"view_chart_{t['symbol']}")])
    kb.append([InlineKeyboardButton("🔙 Back to Wallet", callback_data="wallet_main")])
    
    if q.message.photo:
        await q.message.delete()
        await context.bot.send_message(q.from_user.id, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

async def view_token_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Loading Chart...")
    sym = q.data.split("_")[2]
    token = get_token_details(sym)
    if not token: return
    
    history = token.get("history", [token['price']])
    if len(history) < 2: history = [token['price']] * 5 
    chart_buf = generate_chart_image(sym, history)
    
    caption = (
        f"📊 **{token['name']} ({sym})**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 **Price:** ₹{token['price']}\n"
        f"📉 **Low (24h):** ₹{min(history)}\n"
        f"📈 **High (24h):** ₹{max(history)}\n"
    )
    kb = [
        [InlineKeyboardButton("🟢 BUY", callback_data=f"ask_buy_{sym}"), InlineKeyboardButton("🔴 SELL", callback_data=f"ask_sell_{sym}")],
        [InlineKeyboardButton("🔙 Market", callback_data="wallet_tokens")]
    ]
    await q.message.delete()
    if chart_buf:
        await context.bot.send_photo(q.from_user.id, photo=chart_buf, caption=caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await context.bot.send_message(q.from_user.id, caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ConversationHandler.END

# ==========================================
# 3. FLEXIBLE BUYING / SELLING LOGIC
# ==========================================
async def ask_trade_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    data = q.data.split("_")
    action, sym = data[1], data[2]
    context.user_data['trade_action'] = action
    context.user_data['trade_symbol'] = sym
    
    token = get_token_details(sym)
    uid = q.from_user.id
    wallet = get_user_wallet(uid)
    
    if action == "buy":
        max_buy = int(wallet['balance'] // token['price'])
        msg = f"🟢 **BUY {sym}**\n💰 Price: ₹{token['price']}\n💵 Balance: ₹{wallet['balance']:.2f}\n🛒 Max Buy: **{max_buy}**\n\n🔢 **Type Amount to Buy (e.g. 5):**"
    else: 
        owned = wallet.get('holdings', {}).get(sym, 0)
        msg = f"🔴 **SELL {sym}**\n💰 Price: ₹{token['price']}\n🎒 You own: **{owned}**\n\n🔢 **Type Amount to Sell:**"

    if q.message.photo:
        await q.message.delete()
        await context.bot.send_message(uid, msg, parse_mode="Markdown")
    else:
        await q.edit_message_text(msg, parse_mode="Markdown")
    return TRADE_AMOUNT

async def execute_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    try:
        qty = int(text)
        if qty <= 0: raise ValueError
    except:
        await update.message.reply_text("❌ Invalid quantity.")
        return TRADE_AMOUNT

    action = context.user_data.get('trade_action')
    sym = context.user_data.get('trade_symbol')
    token = get_token_details(sym)
    wallet = get_user_wallet(uid)
    
    if action == "buy":
        cost = qty * token['price']
        if wallet['balance'] >= cost:
            trade_token(uid, sym, qty, token['price'], is_buy=True)
            await update.message.reply_text(f"✅ **BOUGHT!**\n➕ {qty} {sym}\n➖ ₹{cost:.2f}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Chart", callback_data=f"view_chart_{sym}")]]))
        else:
            await update.message.reply_text("❌ **Insufficient Funds.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Chart", callback_data=f"view_chart_{sym}")]]))

    elif action == "sell":
        owned = wallet.get('holdings', {}).get(sym, 0)
        if owned >= qty:
            earnings = qty * token['price']
            trade_token(uid, sym, qty, token['price'], is_buy=False)
            await update.message.reply_text(f"✅ **SOLD!**\n➖ {qty} {sym}\n➕ ₹{earnings:.2f}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Chart", callback_data=f"view_chart_{sym}")]]))
        else:
            await update.message.reply_text("❌ **Insufficient Tokens.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Chart", callback_data=f"view_chart_{sym}")]]))

    return ConversationHandler.END

# ==========================================
# 4. DEPOSIT FLOW
# ==========================================
async def start_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("₹100", callback_data="dep_amt_100"), InlineKeyboardButton("₹200", callback_data="dep_amt_200")],
        [InlineKeyboardButton("₹500", callback_data="dep_amt_500"), InlineKeyboardButton("₹1000", callback_data="dep_amt_1000")],
        [InlineKeyboardButton("₹5000", callback_data="dep_amt_5000"), InlineKeyboardButton("🔙 Cancel", callback_data="wallet_main")]
    ]
    if q.message.photo: await q.message.delete(); await context.bot.send_message(q.from_user.id, "➕ **DEPOSIT**\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    else: await q.edit_message_text("➕ **DEPOSIT**\nSelect Amount:", reply_markup=InlineKeyboardMarkup(kb))
    return DEP_AMOUNT

async def select_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "wallet_main": return await wallet_command(update, context)
    context.user_data['dep_amount'] = int(q.data.split("_")[2])
    kb = [[InlineKeyboardButton("📲 UPI", callback_data="dep_method_upi")]]
    await q.edit_message_text(f"💳 Amount: ₹{context.user_data['dep_amount']}\nSelect Method:", reply_markup=InlineKeyboardMarkup(kb))
    return DEP_METHOD

async def show_qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    amount = context.user_data['dep_amount']
    
    # Generate and store a unique Transaction ID for the next step
    tn = f"TXN{int(time.time())}{q.from_user.id}"
    context.user_data['dep_tn'] = tn 
    
    pa_encoded = "akshayajith%40fam"
    pn_encoded = "GrowwMutual%20Ltd" 
    
    dynamic_qr_url = f"https://api.qrserver.com/v1/create-qr-code/?data=upi%3A%2F%2Fpay%3Fpa%3D{pa_encoded}%26pn%3D{pn_encoded}%26am%3D{amount}%26tn%3D{tn}&size=300x300"
    
    caption = (
        f"🧾 **GrowwMutual E-Invoice**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 **Billed To:** {q.from_user.first_name}\n"
        f"🆔 **Txn ID:** `{tn}`\n"
        f"💰 **Amount Due:** ₹{amount}\n"
        f"━━━━━━━━━━━━━━\n"
        f"1️⃣ Scan the dynamic QR code above.\n"
        f"2️⃣ Complete the payment via any UPI app.\n"
        f"3️⃣ Click 'I Have Paid' below."
    )
    
    kb = [
        [InlineKeyboardButton("✅ I Have Paid", callback_data="dep_paid")],
        [InlineKeyboardButton("❌ Cancel Order", callback_data="wallet_main")]
    ]
    await q.message.delete()
    
    try: 
        await context.bot.send_photo(
            q.from_user.id, 
            photo=dynamic_qr_url, 
            caption=caption, 
            reply_markup=InlineKeyboardMarkup(kb), 
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Dynamic QR Error: {e}")
        await context.bot.send_message(
            q.from_user.id, 
            f"⚠️ **QR Generation Error**\nPlease try again later.\n\n{caption}", 
            reply_markup=InlineKeyboardMarkup(kb), 
            parse_mode="Markdown"
        )
        
    return DEP_UTR

async def ask_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This now bypasses asking for text and immediately submits the payment
    q = update.callback_query
    await q.answer()
    
    uid = q.from_user.id
    amt = context.user_data.get('dep_amount')
    tn = context.user_data.get('dep_tn', 'UNKNOWN_TXN')
    
    # Create the transaction in the DB with the generated tn instead of a UTR
    tx_id = create_transaction(uid, "deposit", amt, "Dynamic UPI QR", tn)
    
    kb_admin = InlineKeyboardMarkup([
        [InlineKeyboardButton("Accept", callback_data=f"adm_dep_ok_{tx_id}"), 
         InlineKeyboardButton("Reject", callback_data=f"adm_dep_no_{tx_id}")]
    ])
    
    # Send directly to admin
    await context.bot.send_message(
        ADMIN_ID, 
        f"📥 **DEPOSIT REQUEST**\nUser: {uid}\nAmt: ₹{amt}\nTxn ID: `{tn}`\n*(Check your bank statement for this Txn ID)*", 
        reply_markup=kb_admin, 
        parse_mode="Markdown"
    )
    
    msg = f"✅ **Payment Submitted!**\n\nYour Transaction ID is `{tn}`.\nPlease wait while our system verifies your payment."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="back_home")]])
    
    if q.message.photo: 
        await q.message.delete()
        await context.bot.send_message(uid, msg, reply_markup=kb, parse_mode="Markdown")
    else: 
        await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
        
    return ConversationHandler.END

async def receive_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kept here so main.py does not throw an import error, but will no longer be reached.
    return ConversationHandler.END

# ==========================================
# 5. WITHDRAW FLOW
# ==========================================
async def start_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    bal = get_user_wallet(uid)['balance']
    
    if bal < 100:
        msg, kb = "❌ Min withdrawal is ₹100.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="wallet_main")]])
        if q.message.photo: await q.message.delete(); await context.bot.send_message(uid, msg, reply_markup=kb)
        else: await q.edit_message_text(msg, reply_markup=kb)
        return ConversationHandler.END
        
    kb = [[InlineKeyboardButton(f"100% (₹{int(bal)})", callback_data=f"wd_amt_{int(bal)}")], [InlineKeyboardButton("🔙 Cancel", callback_data="wallet_main")]]
    msg = f"📤 **WITHDRAWAL**\nBalance: ₹{bal}\nSelect Amount:"
    if q.message.photo: await q.message.delete(); await context.bot.send_message(uid, msg, reply_markup=InlineKeyboardMarkup(kb))
    else: await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    return WD_AMOUNT

async def select_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "wallet_main": return await wallet_command(update, context)
    context.user_data['wd_amount'] = int(q.data.split("_")[2])
    kb = [[InlineKeyboardButton("UPI", callback_data="wd_method_UPI"), InlineKeyboardButton("USDT", callback_data="wd_method_USDT")]]
    await q.edit_message_text(f"💸 Select Receiving Method:", reply_markup=InlineKeyboardMarkup(kb))
    return WD_METHOD

async def ask_withdraw_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data['wd_method'] = q.data.split("_")[2]
    await q.edit_message_text(f"📝 **Enter Details for {context.user_data['wd_method']}:**")
    return WD_DETAILS

async def process_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    details, uid, amt = update.message.text, update.effective_user.id, context.user_data['wd_amount']
    if get_user_wallet(uid)['balance'] < amt: return ConversationHandler.END
    
    update_wallet_balance(uid, -amt)
    tx_id = create_transaction(uid, "withdraw", amt, context.user_data['wd_method'], details)
    
    kb_admin = InlineKeyboardMarkup([[InlineKeyboardButton("Approve", callback_data=f"adm_wd_ok_{tx_id}"), InlineKeyboardButton("Reject", callback_data=f"adm_wd_no_{tx_id}")]])
    await context.bot.send_message(ADMIN_ID, f"📤 **WITHDRAW**\nUser: {uid}\nAmt: ₹{amt}\nDet: {details}", reply_markup=kb_admin)
    await update.message.reply_text("✅ **Requested.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="back_home")]]))
    return ConversationHandler.END

# ==========================================
# 6. ADMIN & NEW FEATURE HANDLERS
# ==========================================
async def admin_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")
    action, decision, tx_id = parts[1], parts[2], parts[3]
    tx = get_transaction(tx_id)
    if not tx or tx['status'] != 'pending': return await q.answer("❌ Already processed.", show_alert=True)

    uid, amt = tx['user_id'], tx['amount']
    if action == "dep": 
        if decision == "ok":
            update_wallet_balance(uid, amt)
            update_transaction_status(tx_id, "completed")
            record_first_deposit(uid) 
            await context.bot.send_message(uid, f"✅ Deposit ₹{amt} Approved")
        else:
            update_transaction_status(tx_id, "rejected")
            await context.bot.send_message(uid, f"❌ Deposit ₹{amt} Rejected")
            
    elif action == "wd":
        if decision == "ok":
            update_transaction_status(tx_id, "completed")
            await context.bot.send_message(uid, f"✅ Withdraw ₹{amt} Sent")
        else:
            update_wallet_balance(uid, amt); update_transaction_status(tx_id, "rejected")
            await context.bot.send_message(uid, f"❌ Withdraw ₹{amt} Rejected (Refunded)")
    await q.edit_message_text(f"Processed: {action} {decision}")

async def token_rig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        update_token_price(context.args[0].upper(), float(context.args[1]))
        await update.message.reply_text(f"✅ Rigged. Price anchored.")
    except: await update.message.reply_text("❌ Usage: `/token_rig SYM PRICE`")

async def token_roi_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    roi_data = get_token_roi_list()
    if not roi_data:
        return await update.message.reply_text("❌ Error loading market data.")
        
    msg = "📈 **TOKEN ROI PERFORMANCE**\n━━━━━━━━━━━━━━\n"
    for item in roi_data:
        symbol = item['symbol']
        pct = item['roi_percent']
        price = item['current_price']
        
        icon = "🚀" if pct > 0 else "🔻" if pct < 0 else "➖"
        sign = "+" if pct > 0 else ""
        
        msg += f"{icon} **{symbol}**: {sign}{pct:.2f}% (₹{price})\n"
        
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- NEW: CURRENT VALUE LOCKED COMMAND ---
async def token_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    stats = get_current_token_stats()
    
    if not stats:
        return await update.message.reply_text("📊 No tokens are currently held by users.")
        
    msg = "🏆 **TOKEN VALUE LOCKED (TVL)**\n*Current fiat value invested right now*\n━━━━━━━━━━━━━━\n"
    for s in stats:
        msg += f"🔹 **{s['symbol']}**: ₹{s['current_value']:.2f} ({int(s['total_held'])} tokens)\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- NEW: CURRENT PROFIT RANKING COMMAND ---
async def token_profits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    stats = get_platform_profit_by_token()
    
    if not stats:
        return await update.message.reply_text("📊 No profit data available yet.")
        
    msg = "💰 **REAL-TIME USER PROFITS**\n*Which tokens users are profiting most on*\n━━━━━━━━━━━━━━\n"
    for s in stats:
        icon = "🟢" if s['net_profit'] >= 0 else "🔴"
        sign = "+" if s['net_profit'] >= 0 else ""
        msg += f"{icon} **{s['symbol']}**: {sign}₹{s['net_profit']:.2f} Profit\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- USER COMMANDS (REFERRAL, STATS, GIFTS) ---

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data = get_user_data(uid)
    bot_username = context.bot.username
    
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
    ref_count = user_data.get("referral_count", 0)
    
    msg = (
        f"🤝 **INVITE & EARN**\n"
        f"━━━━━━━━━━━━━━\n"
        f"Share your link to invite friends. You will receive **₹50** instantly for every successful new signup!\n\n"
        f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
        f"👥 **Your Referrals:** {ref_count}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def daily_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_daily_stats()
    msg = (
        f"📊 **DAILY STATS (Today)**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 New Registered Members: **{stats['new_users']}**\n"
        f"💰 First-Time Depositors: **{stats['first_deposits']}**\n"
        f"*(Stats will automatically reset at midnight)*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def gen_gift_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        amount = float(context.args[0])
        code = generate_gift_code(amount)
        if code:
            await update.message.reply_text(f"🎁 **GIFT CODE GENERATED**\n\nCode: `{code}`\nValue: ₹{amount}\n\nUsers can use `/redeem <code>`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Database error.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/gen_gift AMOUNT`")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_data(uid) 
    try:
        code = context.args[0]
        success, amount = redeem_gift_code(uid, code)
        if success:
            await update.message.reply_text(f"🎉 **SUCCESS!**\nYou redeemed ₹{amount} to your wallet.")
        else:
            await update.message.reply_text("❌ Invalid or already used Gift Code.")
    except IndexError:
        await update.message.reply_text("❌ Usage: `/redeem CODE`")
