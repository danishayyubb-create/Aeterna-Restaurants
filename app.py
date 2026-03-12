import streamlit as st
import json
import os
import hashlib
import secrets
import uuid
from datetime import datetime
import re
import threading
from flask import Flask, request, jsonify
import qrcode
from io import BytesIO
from pywa import WhatsApp
import sqlite3

# database helper functions
from db_helper import (
    init_db, apply_migration, signup_user, login_user, hash_password, verify_password, 
    get_user_info, update_user_info, get_user_id, get_inventory, add_inventory_item, 
    get_orders, save_order, update_order_status, is_subscription_valid, 
    get_subscription_details, update_subscription
)

# initialize sqlite database file and tables
init_db()
apply_migration()

# ================================
# WHATSAPP INTEGRATION SETUP
# ================================

app = Flask(__name__)

# WhatsApp setup - you'll need to provide your API token and phone number
# For now, using placeholder - replace with actual credentials
WA_TOKEN = os.getenv('WA_TOKEN', 'your_whatsapp_api_token_here')
WA_PHONE_ID = os.getenv('WA_PHONE_ID', 'your_phone_id_here')
WA_VERIFY_TOKEN = os.getenv('WA_VERIFY_TOKEN', 'your_verify_token_here')

wa = WhatsApp(
    token=WA_TOKEN,
    phone_id=WA_PHONE_ID
)

# Global variables for order processing
current_orders = {}  # phone -> order_in_progress

# ================================
# DATA MANAGEMENT FUNCTIONS (JSON-backed helpers remain for legacy/restaurant data)
# ================================

# note: password hashing & verification are handled in db_helper, imported above.

def load_users():
    if os.path.exists('users.json'):
        with open('users.json', 'r') as f:
            return json.load(f)
    return {"users": []}

def save_users(data):
    with open('users.json', 'w') as f:
        json.dump(data, f, indent=4)

def load_restaurants():
    if os.path.exists('restaurants.json'):
        with open('restaurants.json', 'r') as f:
            return json.load(f)
    return {"restaurants": []}

def save_restaurants(data):
    with open('restaurants.json', 'w') as f:
        json.dump(data, f, indent=4)

def get_restaurant_name(restaurant_id):
    """Return the name of a restaurant given its ID.
    Falls back to a placeholder if the ID isn't found.
    """
    # restaurants_data will be initialized later, but that's fine as
    # the function is only called after loading.
    for r in restaurants_data.get("restaurants", []):
        if r["id"] == restaurant_id:
            return r["name"]
    return "Unknown Restaurant"

def load_inventory():
    if os.path.exists('inventory.json'):
        with open('inventory.json', 'r') as f:
            return json.load(f)
    return {"inventory": []}

def save_inventory(data):
    with open('inventory.json', 'w') as f:
        json.dump(data, f, indent=4)

def load_orders():
    if os.path.exists('orders.json'):
        with open('orders.json', 'r') as f:
            return json.load(f)
    return {"orders": []}

def save_orders(data):
    with open('orders.json', 'w') as f:
        json.dump(data, f, indent=4)

def send_status_update(message, restaurant_id, phone_number=None):
    """Send status update to customer's chat (simulating WhatsApp)"""
    if f'chat_messages_{restaurant_id}' in st.session_state:
        st.session_state[f'chat_messages_{restaurant_id}'].append({"role": "assistant", "content": message})
    
    # Send WhatsApp message if phone number provided
    if phone_number:
        send_whatsapp_notification(phone_number, message)

# ================================
# FLASK ROUTES FOR WHATSAPP
# ================================

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """Verify webhook for WhatsApp"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == WA_VERIFY_TOKEN:
        return challenge
    return 'Forbidden', 403

@app.route('/webhook', methods=['POST'])
def handle_message():
    """Handle incoming WhatsApp messages"""
    data = request.get_json()
    
    if data and 'entry' in data:
        for entry in data['entry']:
            for change in entry.get('changes', []):
                messages = change.get('value', {}).get('messages', [])
                for message in messages:
                    if message['type'] == 'text':
                        from_number = message['from']
                        text = message['text']['body']
                        
                        # Process the message using existing AI logic
                        response = process_whatsapp_message(from_number, text)
                        
                        # Send response back
                        wa.send_message(
                            to=from_number,
                            text=response
                        )
    
    return jsonify({'status': 'ok'})

@app.route('/qr')
def qr_code():
    """Display QR code for WhatsApp setup"""
    try:
        # Try to get the actual QR code from WhatsApp API
        qr_data = wa.get_qr_code()
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf.getvalue(), 200, {'Content-Type': 'image/png'}
    except Exception as e:
        # Fallback to static QR if API not configured
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data("whatsapp://send?phone=03703795149")
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf.getvalue(), 200, {'Content-Type': 'image/png'}

def process_whatsapp_message(from_number, text):
    """Process WhatsApp message using existing AI logic"""
    global current_orders
    
    # Load data
    inventory_data = load_inventory()
    orders_data = load_orders()
    
    # Get default restaurant
    restaurants_data = load_restaurants()
    restaurant_id = restaurants_data["restaurants"][0]["id"] if restaurants_data["restaurants"] else None
    restaurant_name = get_restaurant_name(restaurant_id) if restaurant_id else "Restaurant"
    
    # Get or create order in progress for this number
    if from_number not in current_orders:
        current_orders[from_number] = []
    
    order_in_progress = current_orders[from_number]
    chat_messages = []  # Not used for WhatsApp
    
    # For WhatsApp, skip phone number logic since we have it
    text_lower = text.lower().strip()
    if "confirm" in text_lower and order_in_progress:
        # Directly confirm the order
        total = sum(item['price'] * item['quantity'] for item in order_in_progress)
        items_summary = "\n".join([f"• {item['quantity']}x {item['name']} - ${item['quantity'] * item['price']:.2f}" for item in order_in_progress])
        order = {
            "id": str(uuid.uuid4()),
            "restaurant_id": restaurant_id,
            "customer": from_number,
            "items": order_in_progress.copy(),
            "total": round(total, 2),
            "timestamp": datetime.now().isoformat(),
            "status": "confirmed",
            "ready": False,
            "ready_time": None,
            "chef_time": None,
            "rider_status": None
        }
        orders_data["orders"].append(order)
        save_orders(orders_data)
        response = f"Order Summary:\n\n{items_summary}\n\nTotal Amount: ${total:.2f}\n\n🎉 Order Confirmed! Your order is being prepared. Thank you for ordering from {restaurant_name}!"
        order_in_progress.clear()
        return response
    elif "confirm" in text_lower:
        return "Your cart is empty. Add some items first!"
    
    # Use existing AI logic for other messages
    response = generate_ai_response(text, restaurant_name, inventory_data, restaurant_id, order_in_progress, chat_messages)
    
    return response

def send_whatsapp_notification(phone_number, message):
    """Send WhatsApp message to customer"""
    try:
        wa.send_message(
            to=phone_number,
            text=message
        )
        return True
    except Exception as e:
        print(f"Failed to send WhatsApp message: {e}")
        return False

# ================================
# AI RESPONSE GENERATION
# ================================

def extract_quantity(text):
    """Extract quantity from user message (e.g., '2 burgers' -> 2)"""
    match = re.search(r'(\d+)\s+', text)
    return int(match.group(1)) if match else 1

def generate_ai_response(user_message, restaurant_name, inventory_data, restaurant_id, order_in_progress, chat_messages):
    """Generate intelligent AI responses with upselling"""
    items = [i for i in inventory_data["inventory"] if i["restaurant_id"] == restaurant_id and i["stock"] > 0]
    user_msg_lower = user_message.lower().strip()
    
    # First greeting
    if len(chat_messages) == 1:  # First user message
        menu_text = "\n".join([f"🍽️ {item['name']} ({item['category']}) - ${item['price']:.2f}" for item in items])
        return f"👋 Welcome to {restaurant_name}!\n\nHere's what we offer:\n\n{menu_text}\n\nWhat would you like to order today?"
    
    # Handle confirmation
    if "confirm" in user_msg_lower:
        if st.session_state.get('waiting_for_phone', False):
            # This message should be the phone number
            phone = user_message.strip()
            if phone:
                st.session_state['phone_number'] = phone
                st.session_state['waiting_for_phone'] = False
                # Now proceed to confirm the order
                if order_in_progress:
                    total = sum(item['price'] * item['quantity'] for item in order_in_progress)
                    items_summary = "\n".join([f"• {item['quantity']}x {item['name']} - ${item['quantity'] * item['price']:.2f}" for item in order_in_progress])
                    order = {
                        "id": str(uuid.uuid4()),
                        "restaurant_id": restaurant_id,
                        "customer": st.session_state['phone_number'],
                        "items": order_in_progress.copy(),
                        "total": round(total, 2),
                        "timestamp": datetime.now().isoformat(),
                        "status": "confirmed",
                        "ready": False,
                        "ready_time": None,
                        "chef_time": None,
                        "rider_status": None
                    }
                    orders_data["orders"].append(order)
                    save_orders(orders_data)
                    response = f"Order Summary:\n\n{items_summary}\n\nTotal Amount: ${total:.2f}\n\n🎉 Order Confirmed! Your order is being prepared. Thank you for ordering from {restaurant_name}!"
                    order_in_progress.clear()
                    st.session_state['phone_number'] = None  # Reset for next order
                    return response
                else:
                    return "Your cart is empty."
            else:
                return "Please provide a valid WhatsApp number."
        elif order_in_progress:
            if not st.session_state.get('phone_number'):
                st.session_state['waiting_for_phone'] = True
                return "Before confirming your order, please provide your WhatsApp number for order updates."
            else:
                # Already have phone, confirm
                total = sum(item['price'] * item['quantity'] for item in order_in_progress)
                items_summary = "\n".join([f"• {item['quantity']}x {item['name']} - ${item['quantity'] * item['price']:.2f}" for item in order_in_progress])
                order = {
                    "id": str(uuid.uuid4()),
                    "restaurant_id": restaurant_id,
                    "customer": st.session_state['phone_number'],
                    "items": order_in_progress.copy(),
                    "total": round(total, 2),
                    "timestamp": datetime.now().isoformat(),
                    "status": "confirmed",
                    "ready": False,
                    "ready_time": None,
                    "chef_time": None,
                    "rider_status": None
                }
                orders_data["orders"].append(order)
                save_orders(orders_data)
                response = f"Order Summary:\n\n{items_summary}\n\nTotal Amount: ${total:.2f}\n\n🎉 Order Confirmed! Your order is being prepared. Thank you for ordering from {restaurant_name}!"
                order_in_progress.clear()
                st.session_state['phone_number'] = None  # Reset
                return response
        else:
            return "Your cart is empty. Add some items first!"
    
    # Cancel order
    if "cancel" in user_msg_lower:
        order_in_progress.clear()
        return "Cart cleared."
    
    # View menu again
    if "menu" in user_msg_lower:
        menu_text = "\n".join([f"🍽️ {item['name']} ({item['category']}) - ${item['price']:.2f}" for item in items])
        return f"Here's our full menu:\n\n{menu_text}"
    
    # View current order
    if "cart" in user_msg_lower or "order" in user_msg_lower and order_in_progress:
        if order_in_progress:
            items_summary = "\n".join([f"• {item['quantity']}x {item['name']} - ${item['quantity'] * item['price']:.2f}" for item in order_in_progress])
            total = sum(item['price'] * item['quantity'] for item in order_in_progress)
            return f"📦 Your Current Order:\n\n{items_summary}\n\n💰 Total: ${total:.2f}\n\nType 'confirm' to order or 'cancel' to reset."
        return "Your cart is empty. Start ordering!"
    
    # Check if user is ordering an item
    for item in items:
        item_name_clean = item['name'].lower().strip()
        if user_msg_lower in item_name_clean:
            # Add to cart
            existing = next((x for x in order_in_progress if x['name'] == item['name']), None)
            quantity = extract_quantity(user_msg_lower) or 1
            if existing:
                existing['quantity'] += quantity
                return f"Added {item['name']} to your cart! (Updated quantity to {existing['quantity']}) Type \"confirm\" to see your bill or \"menu\" to add more."
            else:
                order_in_progress.append({
                    "id": str(uuid.uuid4()),
                    "name": item['name'],
                    "price": item['price'],
                    "quantity": quantity
                })
                return f"Added {item['name']} to your cart! Type \"confirm\" to see your bill or \"menu\" to add more."
    
    # Default response
    return "I'm sorry, I didn't quite understand. 😊\n\nYou can:\n• Say an item name to order (e.g., 'burger')\n• Type 'menu' to see all items\n• Type 'confirm' to place your order\n• Type 'cancel' to reset your order"

# ================================
# INITIALIZATION
# ================================

users_data = load_users()
restaurants_data = load_restaurants()
inventory_data = load_inventory()
orders_data = load_orders()

# Create default admin restaurant if none exists
if not restaurants_data["restaurants"]:
    admin_restaurant = {
        "id": str(uuid.uuid4()),
        "name": "Aeterna",
        "theme": "dark",
        "logo_url": ""
    }
    restaurants_data["restaurants"].append(admin_restaurant)
    save_restaurants(restaurants_data)
    default_restaurant_id = admin_restaurant["id"]
else:
    default_restaurant_id = restaurants_data["restaurants"][0]["id"]

# Create sample inventory if empty (only for new users, but we'll add to DB later)
if not inventory_data["inventory"]:
    sample_items = [
        {"id": str(uuid.uuid4()), "name": "Burger", "category": "Main", "price": 10.99, "stock": 20, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Fries", "category": "Side", "price": 3.99, "stock": 30, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Coke", "category": "Drink", "price": 2.99, "stock": 50, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Pizza", "category": "Main", "price": 12.99, "stock": 15, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Salad", "category": "Side", "price": 5.99, "stock": 10, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Water", "category": "Drink", "price": 1.99, "stock": 100, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Ice Cream", "category": "Dessert", "price": 4.99, "stock": 25, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Pasta", "category": "Main", "price": 11.99, "stock": 18, "restaurant_id": default_restaurant_id},
        {"id": str(uuid.uuid4()), "name": "Zinger Burger", "category": "Main", "price": 13.99, "stock": 15, "restaurant_id": default_restaurant_id}
    ]
    inventory_data["inventory"].extend(sample_items)
    save_inventory(inventory_data)

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.role = None
    st.session_state.restaurant_id = None
    st.session_state.restaurant_name = None         # pulled from DB
    st.session_state.whatsapp_number = None        # pulled from DB
    st.session_state.user_id = None                # user ID from DB
    st.session_state.subscription_status = None    # subscription status from DB
    st.session_state.plan_type = None              # plan type from DB
    st.session_state.expiry_date = None            # expiry date from DB
    st.session_state.is_admin = False              # admin status from DB
    st.session_state.subscription_valid = False    # whether subscription is valid
    st.session_state.discount_percentage = 0       # discount percentage from DB
    st.session_state.discount_notes = None         # discount notes from DB
if 'phone_number' not in st.session_state:
    st.session_state.phone_number = None
if 'waiting_for_phone' not in st.session_state:
    st.session_state.waiting_for_phone = False

# Start Flask server in background thread
def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

# Page configuration
st.set_page_config(
    page_title=st.session_state.get("restaurant_name") or "Aeterna Resto AI",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling - Aeterna Gold Theme
st.markdown("""
<style>
    :root {
        --primary-color: #FFD700;  /* Aeterna Gold */
        --secondary-color: #FFA500;  /* Orange accent */
        --background-color: #1a1a1a;  /* Dark background */
        --text-color: #ffffff;  /* White text */
        --card-bg: #2d2d2d;  /* Card background */
    }
    
    .stApp {
        background: linear-gradient(135deg, var(--background-color) 0%, #0f0f0f 100%);
        color: var(--text-color);
    }
    
    .main {
        padding: 2rem;
    }
    
    .sidebar .sidebar-content {
        background: linear-gradient(180deg, var(--card-bg) 0%, var(--background-color) 100%);
        border-right: 2px solid var(--primary-color);
    }
    
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
        animation: slideIn 0.3s ease-in-out;
        background: var(--card-bg);
        border-left: 4px solid var(--primary-color);
    }
    
    @keyframes slideIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .order-card {
        border-left: 4px solid var(--primary-color);
        padding: 1rem;
        background: var(--card-bg);
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    
    .kitchen-order {
        border: 2px solid var(--secondary-color);
        padding: 1.5rem;
        background: var(--card-bg);
        border-radius: 0.75rem;
        margin: 1rem 0;
    }
    
    .ready-badge {
        background: var(--primary-color);
        color: black;
        padding: 0.5rem 1rem;
        border-radius: 2rem;
        font-weight: bold;
    }
    
    .pending-badge {
        background: var(--secondary-color);
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 2rem;
        font-weight: bold;
    }
    
    h1, h2, h3 {
        color: var(--primary-color) !important;
    }
    
    .stButton>button {
        background: var(--primary-color) !important;
        color: black !important;
        border: none !important;
    }
    
    .stTextInput>div>div>input {
        background: var(--card-bg) !important;
        color: var(--text-color) !important;
        border: 1px solid var(--primary-color) !important;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------
# Authentication (login/signup) using sqlite3-backed user table
# ------------------------------
if not st.session_state.logged_in:
    # allow the visitor to choose between logging in or creating a new account
    choice = st.sidebar.radio("Authenticate", ["Login", "Sign Up"], index=0)
    if choice == "Login":
        username = st.sidebar.text_input("Username", key="login_username")
        password = st.sidebar.text_input("Password", type="password", key="login_password")
        if st.sidebar.button("Login"):
            if login_user(username, password):
                # Check subscription validity
                is_valid = is_subscription_valid(username)
                
                st.session_state.logged_in = True
                st.session_state.user = username
                st.session_state.role = "admin"
                st.session_state.subscription_valid = is_valid
                
                # fetch extra fields from DB
                info = get_user_info(username)
                if info:
                    st.session_state.restaurant_name = info.get('restaurant_name')
                    st.session_state.whatsapp_number = info.get('whatsapp_number')
                    st.session_state.subscription_status = info.get('subscription_status')
                    st.session_state.plan_type = info.get('plan_type')
                    st.session_state.expiry_date = info.get('expiry_date')
                    st.session_state.is_admin = info.get('is_admin', False)
                    st.session_state.discount_percentage = info.get('discount_percentage', 0)
                    st.session_state.discount_notes = info.get('discount_notes')
                
                st.session_state.user_id = get_user_id(username)
                st.success("Logged in successfully!")
                st.experimental_rerun()
            else:
                st.error("Invalid username or password")
    else:
        username = st.sidebar.text_input("Choose a username", key="signup_username")
        password = st.sidebar.text_input("Password", type="password", key="signup_password")
        confirm_password = st.sidebar.text_input("Confirm password", type="password", key="signup_confirm")
        restaurant_name = st.sidebar.text_input("Restaurant Name", key="signup_restaurant_name")
        whatsapp_number = st.sidebar.text_input("WhatsApp Number", key="signup_whatsapp")
        referral_code = st.sidebar.text_input("Referral/Coupon Code (Optional)", key="signup_referral", placeholder="e.g., DANISH50")
        
        if st.sidebar.button("Sign Up"):
            if not username or not password:
                st.error("Username and password are required")
            elif password != confirm_password:
                st.error("Passwords do not match")
            else:
                # Process referral code
                plan_type = "Basic"
                discount_percentage = 0
                discount_notes = None
                
                if referral_code == "DANISH50":
                    plan_type = "Pro"
                    discount_percentage = 50
                    discount_notes = "50% discount applied with DANISH50 coupon"
                
                # Sign up with subscription details
                if signup_user(
                    username, password, 
                    restaurant_name=restaurant_name, 
                    whatsapp_number=whatsapp_number,
                    plan_type=plan_type,
                    discount_percentage=discount_percentage,
                    discount_notes=discount_notes
                ):
                    st.success(f"Account created! {f'Pro plan with 50% discount applied!' if plan_type == 'Pro' else 'Basic plan activated.'} Please log in.")
                else:
                    st.error("Username already exists")

# ------------------------------
# Main content selection
# ------------------------------
if st.session_state.logged_in:
    # Check subscription status - if expired and not admin, show payment required page
    if not st.session_state.subscription_valid and not st.session_state.is_admin:
        # Payment Required Page
        st.markdown("""
        <style>
            .payment-container {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 80vh;
                text-align: center;
                padding: 2rem;
            }
            
            .payment-header {
                color: #FFD700;
                font-size: 3rem;
                font-weight: bold;
                margin-bottom: 1rem;
                animation: fadeIn 1s ease-in;
            }
            
            .payment-title {
                color: #FFD700;
                font-size: 2.5rem;
                font-weight: bold;
                margin: 1rem 0;
            }
            
            .payment-message {
                color: #ffffff;
                font-size: 1.2rem;
                margin: 1rem 0;
                max-width: 600px;
            }
            
            .payment-status {
                background: #2d2d2d;
                border: 2px solid #FFD700;
                border-radius: 1rem;
                padding: 2rem;
                margin: 2rem 0;
                max-width: 500px;
            }
            
            .status-label {
                color: #FFA500;
                font-size: 1.1rem;
                font-weight: bold;
                margin: 0.5rem 0;
            }
            
            .status-value {
                color: #FFD700;
                font-size: 1.5rem;
                font-weight: bold;
                margin: 0.5rem 0;
            }
            
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(-20px); }
                to { opacity: 1; transform: translateY(0); }
            }
        </style>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="payment-container">', unsafe_allow_html=True)
        st.markdown('<div class="payment-header">⚠️</div>', unsafe_allow_html=True)
        st.markdown('<div class="payment-title">Subscription Expired</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="payment-message">Hello {st.session_state.user},<br><br>Your subscription has expired. To continue using Aeterna Restaurants, please renew your subscription.</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="payment-status">', unsafe_allow_html=True)
        st.markdown(f'<div class="status-label">Current Plan:</div><div class="status-value">{st.session_state.plan_type or "Basic"}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="status-label">Expiry Date:</div><div class="status-value">{st.session_state.expiry_date or "N/A"}</div>', unsafe_allow_html=True)
        st.markdown('<div class="status-label">Subscription Status:</div><div class="status-value">🔴 EXPIRED</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write("")
        with col2:
            if st.button("💳 Renew Subscription", use_container_width=True):
                st.info("🚀 Subscription renewal feature coming soon! Contact support@aeterna.ai")
        with col3:
            st.write("")
        
        st.divider()
        if st.button("🚪 Logout"):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.session_state.subscription_valid = False
            st.session_state.is_admin = False
            st.experimental_rerun()
    
    else:
        # Dashboard - normal flow for active subscriptions or admins
        st.sidebar.title(f"Welcome, {st.session_state.user}")
        if st.session_state.role == "admin":
            page = st.sidebar.radio("Navigation", ["Dashboard", "WhatsApp QR Link", "Kitchen View", "Orders View", "Admin Panel", "⚙️ Settings"])
            if page == "Dashboard":
                st.title(f"{st.session_state.restaurant_name or 'Restaurant'} - Aeterna Dashboard")
                st.write("Full access to all features")
                st.subheader("All Restaurants")
                for r in restaurants_data["restaurants"]:
                    st.write(f"Name: {r['name']}, URL: aeterna.ai/menu/{r['id']}")
            elif page == "WhatsApp QR Link":
                st.title("WhatsApp QR Link")
                wa_num = st.session_state.whatsapp_number or "923703795149"
                name_for_url = st.session_state.restaurant_name or "Aeterna"
                target_url = f"https://wa.me/{wa_num}?text=I%20want%20to%20place%20an%20order%20at%20{name_for_url}."
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(target_url)
                qr.make(fit=True)
                img = qr.make_image(fill='black', back_color='white')
                buf = BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                st.image(buf, caption="Scan to open WhatsApp", use_container_width=True)
                if st.button("Open WhatsApp Web"):
                    st.markdown(f"<script>window.open('{target_url}')</script>", unsafe_allow_html=True)
            elif page == "⚙️ Settings":
                st.title("Settings")
                
                # Subscription Information Section
                st.subheader("📋 Subscription Information")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Plan Type", st.session_state.plan_type or "Basic", delta="Status: " + ("🟢 Active" if st.session_state.subscription_valid else "🔴 Expired"))
                with col2:
                    st.metric("Expiry Date", st.session_state.expiry_date or "Lifetime", delta="Admin" if st.session_state.is_admin else "")
                
                if st.session_state.discount_percentage > 0:
                    st.info(f"💰 **Special Discount Applied**: {st.session_state.discount_percentage}% off on your current plan")
                
                st.divider()
                
                # Restaurant Settings
                st.subheader("🏪 Restaurant Settings")
                with st.form("settings_form"):
                    rest_name = st.text_input("Restaurant Name", value=st.session_state.restaurant_name or "", key="settings_restaurant")
                    wa_number = st.text_input("WhatsApp Number", value=st.session_state.whatsapp_number or "", key="settings_whatsapp")
                    submitted = st.form_submit_button("Save Settings")
                    if submitted:
                        if update_user_info(st.session_state.user, restaurant_name=rest_name, whatsapp_number=wa_number):
                            st.session_state.restaurant_name = rest_name
                            st.session_state.whatsapp_number = wa_number
                            st.success("Settings updated successfully!")
                        else:
                            st.error("Failed to update settings")
                
                st.divider()
                
                # Admin Info
                if st.session_state.is_admin:
                    st.success("✨ **Admin Account** - Enjoy unlimited access with no expiry!")

            elif page == "Kitchen View":
                st.title("Kitchen View - All Restaurants")
                selected_restaurant = st.selectbox("Select Restaurant", [r['name'] for r in restaurants_data["restaurants"]], key='admin_kitchen_select')
                restaurant = next(r for r in restaurants_data["restaurants"] if r['name'] == selected_restaurant)
                restaurant_id = restaurant['id']
                confirmed_orders = [o for o in orders_data["orders"] if o["restaurant_id"] == restaurant_id and o.get("status") == "confirmed"]
                if confirmed_orders:
                    for order in confirmed_orders:
                        with st.expander(f"Order #{order['id']} - {order['timestamp']} - Status: {order.get('status', 'Unknown')}"):
                            st.write(f"Customer: {order['customer']}")
                            st.write("Items:")
                            for item in order['items']:
                                st.write(f"- {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']}")
                            st.write(f"Total: ${order['total']}")
                            if st.button("Mark as Ready", key=f"ready_{order['id']}"):
                                order["status"] = "ready"
                                order["ready_time"] = datetime.now().isoformat()
                                save_orders(orders_data)
                                send_status_update("✅ Your order is ready for pickup!", restaurant_id, order["customer"])
                                st.success("Order marked as ready!")
                                st.rerun()
                else:
                    st.write("No confirmed orders.")
            elif page == "Orders View":
                st.title("All Orders")
                if orders_data["orders"]:
                    for order in orders_data["orders"]:
                        restaurant_name = get_restaurant_name(order["restaurant_id"])
                        status = order.get('status', 'Unknown')
                        with st.expander(f"Order #{order['id']} - {restaurant_name} - {order['timestamp']} - Status: {status}"):
                            st.write(f"Customer: {order['customer']}")
                            st.write(f"Status: {status}")
                            if order.get('chef_time'):
                                st.write(f"Chef Time: {order['chef_time']} mins")
                            if order.get('rider_status'):
                                st.write(f"Rider Status: {order['rider_status']}")
                            st.write("Items:")
                            for item in order['items']:
                                st.write(f"- {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}")
                            st.write(f"Total: ${order['total']:.2f}")
                            if order.get('ready_time'):
                                st.write(f"Ready Time: {order['ready_time']}")
                else:
                    st.write("No orders yet.")
            elif page == "Admin Panel":
                st.title("Admin Panel")
                password = st.text_input("Enter Admin Password", type="password", key="admin_password")
                if password == "admin123":
                    tab1, tab2 = st.tabs(["Chef Dashboard", "Rider Panel"])
                
                    with tab1:
                        st.subheader("Chef Interactive Dashboard")
                        confirmed_orders = [o for o in orders_data["orders"] if o.get("status") == "confirmed"]
                        if confirmed_orders:
                            for order in confirmed_orders:
                                with st.expander(f"Order #{order['id']} - {order['timestamp']} - Status: {order.get('status', 'Unknown')}"):
                                    st.write(f"Customer: {order['customer']}")
                                    st.write("Items:")
                                    for item in order['items']:
                                        st.write(f"- {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}")
                                    st.write(f"Total: ${order['total']:.2f}")
                                
                                    # Chef Actions
                                    col1, col2, col3 = st.columns([2, 2, 2])
                                    with col1:
                                        chef_time = st.selectbox("Preparation Time (mins)", [15, 30, 45], key=f"chef_time_{order['id']}", index=1)
                                    with col2:
                                        if st.button("Notify Customer", key=f"notify_{order['id']}"):
                                            order["chef_time"] = chef_time
                                            order["status"] = "preparing"
                                            save_orders(orders_data)
                                            send_status_update(f"👨‍🍳 Chef says your order will be ready in {chef_time} minutes!", order["restaurant_id"], order["customer"])
                                            st.success(f"Notified customer: {chef_time} mins")
                                            st.rerun()
                                    with col3:
                                        if st.button("Order Ready", key=f"ready_{order['id']}"):
                                            order["status"] = "ready"
                                            order["ready_time"] = datetime.now().isoformat()
                                            save_orders(orders_data)
                                            send_status_update("✅ Your order is ready for pickup!", order["restaurant_id"], order["customer"])
                                            st.success("Order marked as ready!")
                                            st.rerun()
                        else:
                            st.write("No confirmed orders.")
                
                    with tab2:
                        st.subheader("Rider & Delivery Panel")
                        ready_orders = [o for o in orders_data["orders"] if o.get("status") == "ready"]
                        if ready_orders:
                            for order in ready_orders:
                                with st.expander(f"Order #{order['id']} - {order['timestamp']} - Status: {order.get('status', 'Unknown')}"):
                                    st.write(f"Customer: {order['customer']}")
                                    st.write("Items:")
                                    for item in order['items']:
                                        st.write(f"- {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']:.2f}")
                                    st.write(f"Total: ${order['total']:.2f}")
                                
                                    # Rider Actions
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        if st.button("Picked Up", key=f"picked_{order['id']}"):
                                            order["rider_status"] = "picked_up"
                                            save_orders(orders_data)
                                            send_status_update("🚴 Rider is on the way with your order!", order["restaurant_id"], order["customer"])
                                            st.success("Order picked up!")
                                            st.rerun()
                                    with col2:
                                        if st.button("Delivered", key=f"delivered_{order['id']}"):
                                            order["status"] = "delivered"
                                            order["rider_status"] = "delivered"
                                            save_orders(orders_data)
                                            send_status_update("🎉 Your order has been delivered! Please rate your experience (1-5 stars).", order["restaurant_id"], order["customer"])
                                            st.success("Order delivered!")
                                            st.rerun()
                        else:
                            st.write("No ready orders for delivery.")
                
                    st.subheader("All Orders Summary")
                    if orders_data["orders"]:
                        table_data = []
                        for order in orders_data["orders"]:
                            items_str = ", ".join([f"{item['quantity']}x {item['name']}" for item in order['items']])
                            table_data.append({
                                "Order ID": order['id'],
                                "Timestamp": order['timestamp'],
                                "Status": order.get('status', 'Unknown'),
                                "Chef Time": order.get('chef_time', 'N/A'),
                                "Rider Status": order.get('rider_status', 'N/A'),
                                "Items": items_str,
                                "Total Price": f"${order['total']:.2f}",
                                "Customer Phone Number": order['customer']
                            })
                        st.table(table_data)
                        if st.button("Clear All Orders"):
                            orders_data["orders"] = []
                            save_orders(orders_data)
                            st.success("All orders cleared!")
                            st.rerun()
                    else:
                        st.write("No orders yet.")
                else:
                    if password:
                        st.error("Incorrect password")
        elif st.session_state.role == "manager":
            restaurant_id = st.session_state.restaurant_id
            restaurant_name = st.session_state.restaurant_name or get_restaurant_name(restaurant_id)
            page = st.sidebar.radio("Navigation", ["Dashboard", "WhatsApp QR Link", "Kitchen View", "Manage Menu", "⚙️ Settings"])
            if page == "Dashboard":
                st.title(f"Kitchen & Sales Dashboard - {restaurant_name}")
                items = [i for i in inventory_data["inventory"] if i["restaurant_id"] == restaurant_id]
                total_items = len(items)
                out_of_stock = len([i for i in items if i["stock"] == 0])
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Total Items", total_items)
                with col2:
                    st.metric("Out of Stock", out_of_stock)
            elif page == "WhatsApp QR Link":
                st.title("WhatsApp QR Link")
                wa_num = st.session_state.whatsapp_number or "923703795149"
                restaurant_name = st.session_state.restaurant_name or get_restaurant_name(restaurant_id)
                target_url = f"https://wa.me/{wa_num}?text=I%20want%20to%20place%20an%20order%20at%20{restaurant_name}."
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(target_url)
                qr.make(fit=True)
                img = qr.make_image(fill='black', back_color='white')
                buf = BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                st.image(buf, caption="Scan to open WhatsApp", use_container_width=True)
                if st.button("Open WhatsApp Web"):
                    st.markdown(f"<script>window.open('{target_url}')</script>", unsafe_allow_html=True)
            elif page == "Kitchen View":
                st.title(f"Kitchen View - {restaurant_name}")
                confirmed_orders = [o for o in orders_data["orders"] if o["restaurant_id"] == restaurant_id and o.get("status") == "confirmed"]
                if confirmed_orders:
                    for order in confirmed_orders:
                        with st.expander(f"Order #{order['id']} - {order['timestamp']} - Status: {order.get('status', 'Unknown')}"):
                            st.write(f"Customer: {order['customer']}")
                            st.write("Items:")
                            for item in order['items']:
                                st.write(f"- {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']}")
                            st.write(f"Total: ${order['total']}")
                            if st.button("Mark as Ready", key=f"ready_{order['id']}"):
                                order["status"] = "ready"
                                order["ready_time"] = datetime.now().isoformat()
                                save_orders(orders_data)
                                send_status_update("✅ Your order is ready for pickup!", restaurant_id, order["customer"])
                                st.success("Order marked as ready!")
                                st.rerun()
                else:
                    st.write("No confirmed orders.")
            elif page == "Manage Menu":
                st.title(f"Manage Menu - {restaurant_name}")
                with st.form("add_item"):
                    name = st.text_input("Item Name", key='add_item_name')
                    category = st.text_input("Category", key='add_item_category')
                    price = st.number_input("Price", min_value=0.0)
                    stock = st.number_input("Stock", min_value=0)
                    submitted = st.form_submit_button("Add Item")
                    if submitted:
                        if name and category:
                            item_id = str(uuid.uuid4())
                            inventory_data["inventory"].append({
                                "id": item_id,
                                "name": name,
                                "category": category,
                                "price": price,
                                "stock": stock,
                                "restaurant_id": restaurant_id
                            })
                            save_inventory(inventory_data)
                            st.success("Item added")
                            st.rerun()
                        else:
                            st.error("Name and category required")
                st.subheader("Current Items")
                items = [i for i in inventory_data["inventory"] if i["restaurant_id"] == restaurant_id]
                for item in items:
                    col1, col2, col3, col4, col5 = st.columns([2,2,1,1,1])
                    with col1:
                        st.write(item["name"])
                    with col2:
                        st.write(item["category"])
                    with col3:
                        st.write(f"${item['price']}")
                    with col4:
                        if item["stock"] < 5:
                            st.write(f"⚠️ {item['stock']}")
                        else:
                            st.write(item["stock"])
                    with col5:
                        if st.button("Delete", key=item["id"]):
                            inventory_data["inventory"] = [i for i in inventory_data["inventory"] if i["id"] != item["id"]]
                            save_inventory(inventory_data)
                            st.rerun()
                st.subheader("Edit Item")
                if items:
                    edit_item_name = st.selectbox("Select item to edit", [i["name"] for i in items], key="edit_select")
                    item = next(i for i in items if i["name"] == edit_item_name)
                    with st.form("edit_item"):
                        name = st.text_input("Item Name", value=item["name"], key='edit_item_name')
                        category = st.text_input("Category", value=item["category"], key='edit_item_category')
                        price = st.number_input("Price", value=item["price"], min_value=0.0)
                        stock = st.number_input("Stock", value=item["stock"], min_value=0)
                        submitted = st.form_submit_button("Update Item")
                        if submitted:
                            item["name"] = name
                            item["category"] = category
                            item["price"] = price
                            item["stock"] = stock
                            save_inventory(inventory_data)
                            st.success("Item updated")
                            st.rerun()
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.session_state.role = None
            st.session_state.restaurant_id = None
            st.rerun()
    else:
    # public visitor chatbot (no login required)
    restaurant_id = default_restaurant_id
    restaurant_name = get_restaurant_name(restaurant_id)
    st.title(f"Chatbot - {restaurant_name}")
    # initialize guest chat state
    if f'chat_messages_{restaurant_id}' not in st.session_state:
        st.session_state[f'chat_messages_{restaurant_id}'] = []
    if f'order_in_progress_{restaurant_id}' not in st.session_state:
        st.session_state[f'order_in_progress_{restaurant_id}'] = []
    # display previous messages
    for message in st.session_state[f'chat_messages_{restaurant_id}']:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    # input handling
    if prompt := st.chat_input("Type your message...", key=f'chat_input_{restaurant_id}'):
        st.session_state[f'chat_messages_{restaurant_id}'].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        response = generate_ai_response(prompt, restaurant_name, inventory_data, restaurant_id, st.session_state[f'order_in_progress_{restaurant_id}'], st.session_state[f'chat_messages_{restaurant_id}'])
        st.session_state[f'chat_messages_{restaurant_id}'].append({"role": "assistant", "content": response})
        with st.chat_message("assistant"):
            st.markdown(response)