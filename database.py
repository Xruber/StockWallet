import time
import random
import logging
import uuid
import certifi  # <--- NEW: Added certifi to fix SSL Handshake errors
from pymongo import MongoClient
from config import MONGO_URI

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

users_collection = None 
tokens_collection = None       
transactions_collection = None 

try:
    # <--- NEW: Added tlsCAFile=certifi.where() to bypass the TLSV1_ALERT_INTERNAL_ERROR
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    db = client.crypto_wallet_bot_db # Using a new isolated database name
    users_collection = db.users
    tokens_collection = db.tokens             
    transactions_collection = db.transactions 
    logger.info("✅ Successfully connected to Wallet Database.")
except Exception as e:
    logger.error(f"❌ Failed to connect to MongoDB: {e}")

# ==========================================
# 1. USER MANAGEMENT
# ==========================================
def get_user_data(user_id):
    if users_collection is None: return {}
    
    user = users_collection.find_one({"user_id": user_id})
    if user is None:
        user = {
            "user_id": user_id,
            "is_banned": False,
            "wallet": {"balance": 0.0, "holdings": {}, "invested_amt": {}} 
        }
        users_collection.insert_one(user)
        
    if "wallet" not in user:
        user["wallet"] = {"balance": 0.0, "holdings": {}, "invested_amt": {}}
        users_collection.update_one({"user_id": user_id}, {"$set": {"wallet": user["wallet"]}})
        
    return user

# ==========================================
# 2. TOKEN & CHART SYSTEM
# ==========================================
INITIAL_TOKENS = [
    {"symbol": "TET", "name": "Texhet", "price": 10.0, "history": [10.0]},
    {"symbol": "GLL", "name": "Gallium", "price": 5.5, "history": [5.5]},
    {"symbol": "GGC", "name": "GigaCoin", "price": 100.0, "history": [100.0]},
    {"symbol": "LKY", "name": "LOWKEY", "price": 0.5, "history": [0.5]},
    {"symbol": "TSK", "name": "Tasket", "price": 12.0, "history": [12.0]},
    {"symbol": "MKY", "name": "Milkyy", "price": 25.0, "history": [25.0]},
    {"symbol": "HOA", "name": "Hainoka", "price": 8.0, "history": [8.0]},
    {"symbol": "ZDR", "name": "Zendora", "price": 1.2, "history": [1.2]},
    {"symbol": "FLX", "name": "Flux", "price": 45.0, "history": [45.0]},
    {"symbol": "VRT", "name": "Vortex", "price": 150.0, "history": [150.0]},
    {"symbol": "CRM", "name": "Crimson", "price": 7.0, "history": [7.0]},
    {"symbol": "AER", "name": "Aether", "price": 90.0, "history": [90.0]},
    {"symbol": "PLS", "name": "Pulse", "price": 3.3, "history": [3.3]},
    {"symbol": "ION", "name": "Ion", "price": 18.0, "history": [18.0]},
    {"symbol": "NVX", "name": "NovaX", "price": 60.0, "history": [60.0]}
]

def init_tokens():
    if tokens_collection is not None and tokens_collection.count_documents({}) == 0:
        tokens_collection.insert_many(INITIAL_TOKENS)

def get_all_tokens():
    if tokens_collection is None: return []
    tokens = list(tokens_collection.find({}, {"_id": 0}))
    
    # Market Fluctuation Logic
    for t in tokens:
        if random.random() > 0.6: 
            change = random.uniform(0.95, 1.05)
            new_price = round(t['price'] * change, 2)
            tokens_collection.update_one(
                {"symbol": t['symbol']}, 
                {
                    "$set": {"price": new_price},
                    "$push": {"history": {"$each": [new_price], "$slice": -20}}
                }
            )
            t['price'] = new_price 
    return tokens

def get_token_details(symbol):
    if tokens_collection is None: return None
    return tokens_collection.find_one({"symbol": symbol})

def update_token_price(symbol, new_price):
    if tokens_collection is not None:
        tokens_collection.update_one({"symbol": symbol}, {"$set": {"price": float(new_price)}, "$push": {"history": float(new_price)}})

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
# 4. TRANSACTION HISTORY
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

init_tokens()
