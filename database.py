import time
import random
import logging
import uuid
import string
from datetime import date
import certifi
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

users_collection = None 
tokens_collection = None       
transactions_collection = None 
gift_codes_collection = None
stats_collection = None

try:
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    db = client.crypto_wallet_bot_db 
    users_collection = db.users
    tokens_collection = db.tokens             
    transactions_collection = db.transactions 
    gift_codes_collection = db.gift_codes
    stats_collection = db.daily_stats
    logger.info("✅ Successfully connected to Wallet Database.")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {e}")

# ==========================================
# 1. USER, STATS & REFERRAL MANAGEMENT
# ==========================================
def get_today_str():
    return date.today().isoformat()

def record_new_user():
    if stats_collection is None: return
    today = get_today_str()
    stats_collection.update_one({"date": today}, {"$inc": {"new_users": 1}}, upsert=True)

def record_first_deposit(user_id):
    if users_collection is None or stats_collection is None: return
    user = users_collection.find_one({"user_id": user_id})
    if user and not user.get("has_deposited", False):
        users_collection.update_one({"user_id": user_id}, {"$set": {"has_deposited": True}})
        today = get_today_str()
        stats_collection.update_one({"date": today}, {"$inc": {"first_deposits": 1}}, upsert=True)

def get_daily_stats():
    if stats_collection is None: return {"new_users": 0, "first_deposits": 0}
    today = get_today_str()
    stat = stats_collection.find_one({"date": today})
    if not stat: return {"new_users": 0, "first_deposits": 0}
    return {"new_users": stat.get("new_users", 0), "first_deposits": stat.get("first_deposits", 0)}

def get_user_data(user_id, referrer_id=None):
    if users_collection is None: return {}
    
    user = users_collection.find_one({"user_id": user_id})
    
    # NEW USER CREATION + REFERRAL LOGIC
    if user is None:
        user = {
            "user_id": user_id,
            "is_banned": False,
            "has_deposited": False,
            "referred_by": referrer_id,
            "referral_count": 0,
            "wallet": {"balance": 0.0, "holdings": {}, "invested_amt": {}} 
        }
        users_collection.insert_one(user)
        record_new_user()
        
        # Reward the referrer if one exists
        if referrer_id and referrer_id != user_id:
            users_collection.update_one(
                {"user_id": referrer_id},
                {"$inc": {"referral_count": 1, "wallet.balance": 5.0}} # Gives ₹50 per invite
            )
            
    if "wallet" not in user:
        user["wallet"] = {"balance": 0.0, "holdings": {}, "invested_amt": {}}
        users_collection.update_one({"user_id": user_id}, {"$set": {"wallet": user["wallet"]}})
        
    return user

# ==========================================
# 2. TOKEN & CHART SYSTEM (MEAN-REVERSION LOGIC)
# ==========================================
INITIAL_TOKENS = [
    {"symbol": "TET", "name": "Texhet", "price": 10.0, "base_price": 10.0, "history": [10.0]},
    {"symbol": "GLL", "name": "Gallium", "price": 5.5, "base_price": 5.5, "history": [5.5]},
    {"symbol": "GGC", "name": "GigaCoin", "price": 100.0, "base_price": 100.0, "history": [100.0]},
    {"symbol": "LKY", "name": "LOWKEY", "price": 0.5, "base_price": 0.5, "history": [0.5]},
    {"symbol": "TSK", "name": "Tasket", "price": 12.0, "base_price": 12.0, "history": [12.0]},
    {"symbol": "MKY", "name": "Milkyy", "price": 25.0, "base_price": 25.0, "history": [25.0]},
    {"symbol": "HOA", "name": "Hainoka", "price": 8.0, "base_price": 8.0, "history": [8.0]},
    {"symbol": "ZDR", "name": "Zendora", "price": 1.2, "base_price": 1.2, "history": [1.2]},
    {"symbol": "FLX", "name": "Flux", "price": 45.0, "base_price": 45.0, "history": [45.0]},
    {"symbol": "VRT", "name": "Vortex", "price": 150.0, "base_price": 150.0, "history": [150.0]},
    {"symbol": "CRM", "name": "Crimson", "price": 7.0, "base_price": 7.0, "history": [7.0]},
    {"symbol": "AER", "name": "Aether", "price": 90.0, "base_price": 90.0, "history": [90.0]},
    {"symbol": "PLS", "name": "Pulse", "price": 3.3, "base_price": 3.3, "history": [3.3]},
    {"symbol": "ION", "name": "Ion", "price": 18.0, "base_price": 18.0, "history": [18.0]},
    {"symbol": "NVX", "name": "NovaX", "price": 60.0, "base_price": 60.0, "history": [60.0]}
]

def init_tokens():
    if tokens_collection is not None and tokens_collection.count_documents({}) == 0:
        tokens_collection.insert_many(INITIAL_TOKENS)

def get_all_tokens():
    if tokens_collection is None: return []
    return list(tokens_collection.find({}, {"_id": 0}))

def update_market_prices():
    """ Runs every 5 mins. Uses Mean-Reversion to prevent 1000x mooning or crashing to zero. """
    if tokens_collection is None: return
    tokens = list(tokens_collection.find({}))
    
    for t in tokens:
        current_price = t['price']
        base_price = t.get('base_price', current_price) # The anchor price
        
        # Calculate how far we are from the base price
        deviation = (current_price - base_price) / base_price
        
        # If deviation is high, the "rubber band" snaps back (mean reversion)
        reversion_force = -deviation * 0.04 
        
        # Random market noise (max 1.5% fluctuation per 5 mins)
        noise = random.uniform(-0.015, 0.015)
        
        change_percent = reversion_force + noise
        
        # Cap maximum movement per 5 mins to 3% to keep it smooth
        change_percent = max(-0.03, min(0.03, change_percent))
        
        new_price = round(current_price * (1 + change_percent), 2)
        
        # Absolute Hard Limits (Price can never go 10x higher or 90% lower than base)
        if new_price > base_price * 10: new_price = round(base_price * 10, 2)
        if new_price < base_price * 0.1: new_price = round(base_price * 0.1, 2)
        if new_price <= 0.01: new_price = 0.01 
        
        update_data = {"price": new_price}
        if 'base_price' not in t: 
            update_data['base_price'] = t['price']
            
        tokens_collection.update_one(
            {"symbol": t['symbol']}, 
            {
                "$set": update_data,
                "$push": {"history": {"$each": [new_price], "$slice": -30}}
            }
        )

def get_token_details(symbol):
    if tokens_collection is None: return None
    return tokens_collection.find_one({"symbol": symbol})

def update_token_price(symbol, new_price):
    if tokens_collection is not None:
        t = tokens_collection.find_one({"symbol": symbol})
        if t:
            # When admin rigs price, update base_price too so it anchors to the new rig
            tokens_collection.update_one(
                {"symbol": symbol}, 
                {"$set": {"price": float(new_price), "base_price": float(new_price)}, "$push": {"history": float(new_price)}}
            )

def get_token_roi_list():
    """ Calculates % growth of all tokens since inception """
    if tokens_collection is None: return []
    tokens = list(tokens_collection.find({}))
    roi_data = []
    
    for t in tokens:
        current = t['price']
        base = t.get('base_price', current)
        
        if base > 0:
            growth_pct = ((current - base) / base) * 100
        else:
            growth_pct = 0.0
            
        roi_data.append({
            "symbol": t['symbol'],
            "name": t['name'],
            "current_price": current,
            "roi_percent": growth_pct
        })
        
    # Sort highest growth first
    roi_data.sort(key=lambda x: x['roi_percent'], reverse=True)
    return roi_data

# ==========================================
# 3. WALLET FUNCTIONS
# ==========================================
def get_user_wallet(user_id):
    u = get_user_data(user_id)
    return u.get("wallet", {"balance": 0.0, "holdings": {}, "invested_amt": {}})

def update_wallet_balance(user_id, amount):
    if users_collection is not None:
        users_collection.update_one({"user_id": user_id}, {"$inc": {"wallet.balance": float(amount)}})

def trade_token(user_id, symbol, quantity, price, is_buy=True):
    if users_collection is None: return
    cost = float(quantity * price)
    
    if is_buy:
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"wallet.balance": -cost, f"wallet.holdings.{symbol}": quantity, f"wallet.invested_amt.{symbol}": cost}}
        )
    else:
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"wallet.balance": cost, f"wallet.holdings.{symbol}": -quantity}}
        )

# ==========================================
# 4. TRANSACTION & ADMIN HISTORY
# ==========================================
def create_transaction(user_id, tx_type, amount, method, details):
    if transactions_collection is None: return "ERROR"
    tx_id = str(uuid.uuid4())[:8]
    tx_data = {"tx_id": tx_id, "user_id": user_id, "type": tx_type, "amount": float(amount), "method": method, "details": details, "status": "pending", "timestamp": time.time()}
    transactions_collection.insert_one(tx_data)
    return tx_id

def get_user_transactions(user_id, limit=5):
    if transactions_collection is None: return []
    return list(transactions_collection.find({"user_id": user_id}).sort("timestamp", -1).limit(limit))

def get_transaction(tx_id):
    return transactions_collection.find_one({"tx_id": tx_id})

def update_transaction_status(tx_id, status):
    transactions_collection.update_one({"tx_id": tx_id}, {"$set": {"status": status}})

def get_token_investment_stats():
    if users_collection is None: return []
    pipeline = [
        {"$project": {"invested_amt": "$wallet.invested_amt"}},
        {"$addFields": {"invested_array": {"$objectToArray": "$invested_amt"}}},
        {"$unwind": "$invested_array"},
        {"$group": {"_id": "$invested_array.k", "total_invested": {"$sum": "$invested_array.v"}}},
        {"$sort": {"total_invested": -1}}
    ]
    return list(users_collection.aggregate(pipeline))

# ==========================================
# 5. GIFT CODE SYSTEM
# ==========================================
def generate_gift_code(amount):
    if gift_codes_collection is None: return None
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    gift_codes_collection.insert_one({"code": code, "amount": float(amount), "used": False})
    return code

def redeem_gift_code(user_id, code):
    if gift_codes_collection is None: return False, 0
    gc = gift_codes_collection.find_one({"code": code, "used": False})
    if not gc: return False, 0
    gift_codes_collection.update_one({"code": code}, {"$set": {"used": True, "used_by": user_id}})
    update_wallet_balance(user_id, gc["amount"])
    return True, gc["amount"]

init_tokens()
