import sqlite3
import hashlib
import secrets

DB_PATH = "app.db"


def get_connection():
    """Return a new sqlite3 connection (creates file if missing)."""
    conn = sqlite3.connect(DB_PATH)
    return conn


def init_db():
    """Create the users, inventory, and orders tables if they don't already exist."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            restaurant_name TEXT,
            whatsapp_number TEXT,
            subscription_status TEXT DEFAULT 'Active',
            plan_type TEXT DEFAULT 'Basic',
            expiry_date TEXT,
            is_admin BOOLEAN DEFAULT 0,
            discount_percentage REAL DEFAULT 0,
            discount_notes TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            customer TEXT NOT NULL,
            items TEXT NOT NULL,  -- JSON string
            total REAL NOT NULL,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            ready BOOLEAN DEFAULT 0,
            ready_time TEXT,
            chef_time TEXT,
            rider_status TEXT,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    """Hash the password using sha256 with a random salt.

    Returns a tuple of (hash, salt).
    """
    if salt is None:
        salt = secrets.token_hex(16)
    hash_val = hashlib.sha256((salt + password).encode()).hexdigest()
    return hash_val, salt


def verify_password(password, stored_hash, salt):
    """Verify provided password against stored hash + salt."""
    return hashlib.sha256((salt + password).encode()).hexdigest() == stored_hash


def signup_user(username, password, restaurant_name=None, whatsapp_number=None, plan_type="Basic", expiry_date=None, is_admin=False, discount_percentage=0, discount_notes=None):
    """Register a new user in the database.

    Passwords are hashed and salted before storage. Returns True if the
    user was created successfully, False if the username already exists.
    Subscription defaults to 'Active' status.
    """
    hash_val, salt = hash_password(password)
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password_hash, salt, restaurant_name, whatsapp_number, plan_type, expiry_date, is_admin, subscription_status, discount_percentage, discount_notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, hash_val, salt, restaurant_name, whatsapp_number, plan_type, expiry_date, is_admin, "Active", discount_percentage, discount_notes),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # username already exists
        return False
    finally:
        conn.close()


def login_user(username, password):
    """Verify user credentials against the database.

    Returns True if the credentials are valid, False otherwise.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT password_hash, salt FROM users WHERE username = ?",
        (username,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        stored_hash, salt = row
        return verify_password(password, stored_hash, salt)
    return False


def get_user_info(username):
    """Return a dict of user columns for the given username, or None."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT username, restaurant_name, whatsapp_number, subscription_status, plan_type, expiry_date, is_admin, discount_percentage, discount_notes FROM users WHERE username = ?",
        (username,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "username": row[0],
            "restaurant_name": row[1],
            "whatsapp_number": row[2],
            "subscription_status": row[3],
            "plan_type": row[4],
            "expiry_date": row[5],
            "is_admin": bool(row[6]),
            "discount_percentage": row[7],
            "discount_notes": row[8],
        }
    return None


def get_user_id(username):
    """Return the user ID for the given username, or None."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_inventory(user_id):
    """Return list of inventory items for the user."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, category, price, stock FROM inventory WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "category": r[2], "price": r[3], "stock": r[4], "restaurant_id": str(user_id)} for r in rows]

def add_inventory_item(user_id, name, category, price, stock):
    """Add a new inventory item for the user."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO inventory (name, category, price, stock, user_id) VALUES (?, ?, ?, ?, ?)",
              (name, category, price, stock, user_id))
    conn.commit()
    conn.close()

def get_orders(user_id):
    """Return list of orders for the user."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, customer, items, total, timestamp, status, ready, ready_time, chef_time, rider_status FROM orders WHERE user_id = ?",
              (user_id,))
    rows = c.fetchall()
    conn.close()
    import json
    return [{"id": r[0], "customer": r[1], "items": json.loads(r[2]), "total": r[3], "timestamp": r[4], "status": r[5],
             "ready": bool(r[6]), "ready_time": r[7], "chef_time": r[8], "rider_status": r[9]} for r in rows]

def save_order(user_id, order):
    """Save an order for the user."""
    conn = get_connection()
    c = conn.cursor()
    import json
    items_json = json.dumps(order["items"])
    c.execute("INSERT INTO orders (id, customer, items, total, timestamp, status, ready, ready_time, chef_time, rider_status, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (order["id"], order["customer"], items_json, order["total"], order["timestamp"], order["status"],
               order.get("ready", False), order.get("ready_time"), order.get("chef_time"), order.get("rider_status"), user_id))
    conn.commit()
    conn.close()

def update_order_status(order_id, status, ready_time=None, chef_time=None, rider_status=None):
    """Update order status."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE orders SET status = ?, ready_time = ?, chef_time = ?, rider_status = ? WHERE id = ?",
              (status, ready_time, chef_time, rider_status, order_id))
    conn.commit()
    conn.close()

def update_user_info(username, restaurant_name=None, whatsapp_number=None):
    """Update restaurant_name and/or whatsapp_number for a user.

    Any argument left as None will not be changed.
    Returns True if the row was updated, False otherwise (e.g. user not found).
    """
    conn = get_connection()
    c = conn.cursor()
    # build dynamic query
    fields = []
    values = []
    if restaurant_name is not None:
        fields.append("restaurant_name = ?")
        values.append(restaurant_name)
    if whatsapp_number is not None:
        fields.append("whatsapp_number = ?")
        values.append(whatsapp_number)
    if not fields:
        conn.close()
        return False
    values.append(username)
    query = f"UPDATE users SET {', '.join(fields)} WHERE username = ?"
    c.execute(query, tuple(values))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def is_subscription_valid(username):
    """Check if a user's subscription is active.
    
    Returns True if:
    - User is an admin (bypass expiry check), OR
    - User's subscription_status is 'Active' and expiry_date is not passed
    
    Returns False if subscription is expired or invalid.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT subscription_status, expiry_date, is_admin FROM users WHERE username = ?",
        (username,)
    )
    row = c.fetchone()
    conn.close()
    
    if not row:
        return False
    
    subscription_status, expiry_date, is_admin = row
    
    # Admins always have access
    if is_admin:
        return True
    
    # Check subscription status
    if subscription_status != "Active":
        return False
    
    # Check expiry date
    if expiry_date:
        from datetime import datetime
        try:
            expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
            if expiry < datetime.now():
                return False
        except (ValueError, TypeError):
            return False
    
    return True


def get_subscription_details(username):
    """Get subscription details for a user."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT subscription_status, plan_type, expiry_date, is_admin, discount_percentage, discount_notes FROM users WHERE username = ?",
        (username,)
    )
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            "subscription_status": row[0],
            "plan_type": row[1],
            "expiry_date": row[2],
            "is_admin": bool(row[3]),
            "discount_percentage": row[4],
            "discount_notes": row[5],
        }
    return None


def update_subscription(username, subscription_status=None, plan_type=None, expiry_date=None, discount_percentage=None, discount_notes=None):
    """Update subscription details for a user."""
    conn = get_connection()
    c = conn.cursor()
    
    fields = []
    values = []
    
    if subscription_status is not None:
        fields.append("subscription_status = ?")
        values.append(subscription_status)
    if plan_type is not None:
        fields.append("plan_type = ?")
        values.append(plan_type)
    if expiry_date is not None:
        fields.append("expiry_date = ?")
        values.append(expiry_date)
    if discount_percentage is not None:
        fields.append("discount_percentage = ?")
        values.append(discount_percentage)
    if discount_notes is not None:
        fields.append("discount_notes = ?")
        values.append(discount_notes)
    
    if not fields:
        conn.close()
        return False
    
    values.append(username)
    query = f"UPDATE users SET {', '.join(fields)} WHERE username = ?"
    c.execute(query, tuple(values))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def apply_migration():
    """Apply migration to add new columns if they don't exist."""
    conn = get_connection()
    c = conn.cursor()
    try:
        # Check if column exists by trying to query it
        c.execute("SELECT subscription_status FROM users LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        try:
            c.execute("ALTER TABLE users ADD COLUMN subscription_status TEXT DEFAULT 'Active'")
            c.execute("ALTER TABLE users ADD COLUMN plan_type TEXT DEFAULT 'Basic'")
            c.execute("ALTER TABLE users ADD COLUMN expiry_date TEXT")
            c.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            c.execute("ALTER TABLE users ADD COLUMN discount_percentage REAL DEFAULT 0")
            c.execute("ALTER TABLE users ADD COLUMN discount_notes TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            # Columns might already exist
            pass
    finally:
        conn.close()

