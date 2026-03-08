import streamlit as st
import json
import os
import hashlib
import secrets
import uuid
from datetime import datetime
import re

# ================================
# DATA MANAGEMENT FUNCTIONS
# ================================

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    return hashlib.sha256((salt + password).encode()).hexdigest(), salt

def verify_password(password, hash_value, salt):
    return hashlib.sha256((salt + password).encode()).hexdigest() == hash_value

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

def get_restaurant_name(restaurant_id):
    for r in restaurants_data["restaurants"]:
        if r["id"] == restaurant_id:
            return r["name"]
    return "Unknown"

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
                        "status": "received",
                        "ready": False,
                        "ready_time": None
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
                    "status": "received",
                    "ready": False,
                    "ready_time": None
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

# Create sample inventory if empty
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
if 'phone_number' not in st.session_state:
    st.session_state.phone_number = None
if 'waiting_for_phone' not in st.session_state:
    st.session_state.waiting_for_phone = False

# Page configuration
st.set_page_config(
    page_title="Aeterna Resto AI",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling
st.markdown("""
<style>
    :root {
        --primary-color: #FF6B35;
        --secondary-color: #004E89;
        --danger-color: #E63946;
    }
    
    .stApp {
        background: linear-gradient(135deg, #0f0f0f 0%, #1a1a1a 100%);
        color: #ffffff;
    }
    
    .main {
        padding: 2rem;
    }
    
    .sidebar .sidebar-content {
        background: linear-gradient(180deg, #1a1a1a 0%, #2d2d2d 100%);
    }
    
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
        animation: slideIn 0.3s ease-in-out;
    }
    
    @keyframes slideIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .order-card {
        border-left: 4px solid #FF6B35;
        padding: 1rem;
        background: #1a1a1a;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    
    .kitchen-order {
        border: 2px solid #004E89;
        padding: 1.5rem;
        background: #1a1a1a;
        border-radius: 0.75rem;
        margin: 1rem 0;
    }
    
    .ready-badge {
        background: #06D6A0;
        color: black;
        padding: 0.5rem 1rem;
        border-radius: 2rem;
        font-weight: bold;
    }
    
    .pending-badge {
        background: #FF6B35;
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 2rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

if not st.session_state.logged_in:
    st.title("Aeterna Resto AI - Login")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    with tab1:
        username = st.text_input("Username", key='login_username')
        password = st.text_input("Password", type="password", key='login_password')
        if st.button("Login"):
            user_found = False
            for user in users_data["users"]:
                if user["username"] == username:
                    user_found = True
                    entered_hash = hashlib.sha256((user["salt"] + password).encode()).hexdigest()
                    if entered_hash == user["password_hash"]:
                        st.session_state.logged_in = True
                        st.session_state.user = username
                        st.session_state.role = user["role"]
                        st.session_state.restaurant_id = user["restaurant_id"]
                        st.success("Logged in successfully!")
                        st.rerun()
                    else:
                        st.error("Invalid password")
                    break
            if not user_found:
                st.error("User not found")
    with tab2:
        restaurant_name = st.text_input("Restaurant Name", key='signup_restaurant_name')
        theme = st.text_input("Theme", value="dark", key='signup_theme')
        logo_url = st.text_input("Logo URL", value="", key='signup_logo_url')
        username = st.text_input("Manager Username", key='signup_username')
        password = st.text_input("Password", type="password", key='signup_password')
        confirm_password = st.text_input("Confirm Password", type="password", key='signup_confirm_password')
        if st.button("Sign Up"):
            if password != confirm_password:
                st.error("Passwords do not match")
            elif any(u["username"] == username for u in users_data["users"]):
                st.error("Username already exists")
            elif any(r["name"] == restaurant_name for r in restaurants_data["restaurants"]):
                st.error("Restaurant name already exists")
            elif not restaurant_name or not username:
                st.error("Restaurant name and username are required")
            else:
                restaurant_id = str(uuid.uuid4())
                restaurants_data["restaurants"].append({
                    "id": restaurant_id,
                    "name": restaurant_name,
                    "theme": theme,
                    "logo_url": logo_url
                })
                save_restaurants(restaurants_data)
                hash_val, salt = hash_password(password)
                users_data["users"].append({
                    "username": username,
                    "password_hash": hash_val,
                    "salt": salt,
                    "role": "manager",
                    "restaurant_id": restaurant_id
                })
                save_users(users_data)
                st.success("Sign up successful! Please login.")
else:
    st.sidebar.title(f"Welcome, {st.session_state.user}")
    if st.session_state.role == "admin":
        page = st.sidebar.radio("Navigation", ["Dashboard", "WhatsApp Simulation", "Kitchen View", "Orders View", "Admin Panel"])
        if page == "Dashboard":
            st.title("SaaS Super Admin Dashboard")
            st.write("Full access to all features")
            st.subheader("All Restaurants")
            for r in restaurants_data["restaurants"]:
                st.write(f"Name: {r['name']}, URL: aeterna.ai/menu/{r['id']}")
        elif page == "WhatsApp Simulation":
            st.title("WhatsApp Simulation - All Restaurants")
            # Similar to manager, but perhaps select restaurant
            selected_restaurant = st.selectbox("Select Restaurant", [r['name'] for r in restaurants_data["restaurants"]], key='admin_select_restaurant')
            restaurant = next(r for r in restaurants_data["restaurants"] if r['name'] == selected_restaurant)
            restaurant_id = restaurant['id']
            restaurant_name = restaurant['name']
            # Then same chat code as manager
            if f'chat_messages_{restaurant_id}' not in st.session_state:
                st.session_state[f'chat_messages_{restaurant_id}'] = []
            if f'order_in_progress_{restaurant_id}' not in st.session_state:
                st.session_state[f'order_in_progress_{restaurant_id}'] = []
            
            for message in st.session_state[f'chat_messages_{restaurant_id}']:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
            
            if prompt := st.chat_input("Type your message...", key=f'chat_input_{restaurant_id}'):
                st.session_state[f'chat_messages_{restaurant_id}'].append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                
                response = generate_ai_response(prompt, restaurant_name, inventory_data, restaurant_id, st.session_state[f'order_in_progress_{restaurant_id}'], st.session_state[f'chat_messages_{restaurant_id}'])
                st.session_state[f'chat_messages_{restaurant_id}'].append({"role": "assistant", "content": response})
                with st.chat_message("assistant"):
                    st.markdown(response)
                
                st.rerun()
        elif page == "Kitchen View":
            st.title("Kitchen View - All Restaurants")
            selected_restaurant = st.selectbox("Select Restaurant", [r['name'] for r in restaurants_data["restaurants"]], key='admin_kitchen_select')
            restaurant = next(r for r in restaurants_data["restaurants"] if r['name'] == selected_restaurant)
            restaurant_id = restaurant['id']
            pending_orders = [o for o in orders_data["orders"] if o["restaurant_id"] == restaurant_id and not o.get("ready", False)]
            if pending_orders:
                for order in pending_orders:
                    with st.expander(f"Order #{order['id']} - {order['timestamp']}"):
                        st.write(f"Customer: {order['customer']}")
                        st.write("Items:")
                        for item in order['items']:
                            st.write(f"- {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']}")
                        st.write(f"Total: ${order['total']}")
                        if st.button("Mark as Ready", key=f"ready_{order['id']}"):
                            order["ready"] = True
                            order["ready_time"] = datetime.now().isoformat()
                            save_orders(orders_data)
                            st.success("Order marked as ready!")
                            st.rerun()
            else:
                st.write("No pending orders.")
        elif page == "Orders View":
            st.title("All Orders")
            if orders_data["orders"]:
                for order in orders_data["orders"]:
                    restaurant_name = get_restaurant_name(order["restaurant_id"])
                    with st.expander(f"Order #{order['id']} - {restaurant_name} - {order['timestamp']}"):
                        st.write(f"Customer: {order['customer']}")
                        st.write(f"Status: {'Ready' if order.get('ready', False) else 'Pending'}")
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
                st.subheader("All Orders")
                if orders_data["orders"]:
                    table_data = []
                    for order in orders_data["orders"]:
                        items_str = ", ".join([f"{item['quantity']}x {item['name']}" for item in order['items']])
                        table_data.append({
                            "Order ID": order['id'],
                            "Timestamp": order['timestamp'],
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
        restaurant_name = get_restaurant_name(restaurant_id)
        page = st.sidebar.radio("Navigation", ["Dashboard", "WhatsApp Simulation", "Kitchen View", "Manage Menu"])
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
        elif page == "WhatsApp Simulation":
            st.title(f"WhatsApp Simulation - {restaurant_name}")
            # Initialize chat history
            if 'chat_messages' not in st.session_state:
                st.session_state.chat_messages = []
            if 'order_in_progress' not in st.session_state:
                st.session_state.order_in_progress = []

            # Display chat messages
            for message in st.session_state.chat_messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # Chat input
            if prompt := st.chat_input("Type your message...", key='chat_input'):
                # Add user message
                st.session_state.chat_messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                # AI response
                response = generate_ai_response(prompt, restaurant_name, inventory_data, restaurant_id, st.session_state.order_in_progress, st.session_state.chat_messages)
                st.session_state.chat_messages.append({"role": "assistant", "content": response})
                with st.chat_message("assistant"):
                    st.markdown(response)

                st.rerun()
        elif page == "Kitchen View":
            st.title(f"Kitchen View - {restaurant_name}")
            pending_orders = [o for o in orders_data["orders"] if o["restaurant_id"] == restaurant_id and not o.get("ready", False)]
            if pending_orders:
                for order in pending_orders:
                    with st.expander(f"Order #{order['id']} - {order['timestamp']}"):
                        st.write(f"Customer: {order['customer']}")
                        st.write("Items:")
                        for item in order['items']:
                            st.write(f"- {item['name']} x{item['quantity']} - ${item['price'] * item['quantity']}")
                        st.write(f"Total: ${order['total']}")
                        if st.button("Mark as Ready", key=f"ready_{order['id']}"):
                            order["ready"] = True
                            order["ready_time"] = datetime.now().isoformat()
                            save_orders(orders_data)
                            st.success("Order marked as ready!")
                            st.rerun()
            else:
                st.write("No pending orders.")
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