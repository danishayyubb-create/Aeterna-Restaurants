from flask import Flask, request, jsonify
import qrcode
from io import BytesIO
from pywa import WhatsApp
import os
import json
import uuid
from datetime import datetime
import re

app = Flask(__name__)

# WhatsApp setup
WA_TOKEN = os.getenv('WA_TOKEN', 'your_whatsapp_api_token_here')
WA_PHONE_ID = os.getenv('WA_PHONE_ID', 'your_phone_id_here')
WA_VERIFY_TOKEN = os.getenv('WA_VERIFY_TOKEN', 'your_verify_token_here')

wa = WhatsApp(
    token=WA_TOKEN,
    phone_id=WA_PHONE_ID
)

# Global variables for order processing
current_orders = {}  # phone -> order_in_progress

def load_inventory():
    if os.path.exists('inventory.json'):
        with open('inventory.json', 'r') as f:
            return json.load(f)
    return {"inventory": []}

def load_orders():
    if os.path.exists('orders.json'):
        with open('orders.json', 'r') as f:
            return json.load(f)
    return {"orders": []}

def save_orders(data):
    with open('orders.json', 'w') as f:
        json.dump(data, f, indent=4)

def load_restaurants():
    if os.path.exists('restaurants.json'):
        with open('restaurants.json', 'r') as f:
            return json.load(f)
    return {"restaurants": []}

def get_restaurant_name(restaurant_id):
    restaurants_data = load_restaurants()
    for r in restaurants_data.get("restaurants", []):
        if r["id"] == restaurant_id:
            return r["name"]
    return "Unknown Restaurant"

def extract_quantity(text):
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
    # Generate QR code for the phone number
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)