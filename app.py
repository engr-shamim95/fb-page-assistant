import os
import requests
import threading
from flask import Flask, request
from dotenv import load_dotenv
import google.generativeai as genai
from PIL import Image
from io import BytesIO

load_dotenv()

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

import sqlite3
import json
import re

genai.configure(api_key=GEMINI_API_KEY)

# Initialize Database for Orders and History
def init_db():
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id TEXT,
                    customer_name TEXT,
                    phone TEXT,
                    address TEXT,
                    product TEXT,
                    status TEXT DEFAULT 'Pending'
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    sender_id TEXT PRIMARY KEY,
                    history TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    price TEXT,
                    stock_quantity INTEGER
                 )''')
    conn.commit()
    conn.close()

init_db()

def save_history(sender_id, chat):
    try:
        history_list = []
        for content in chat.history:
            parts = []
            for part in content.parts:
                if hasattr(part, 'text') and part.text:
                    parts.append(part.text)
            if parts:
                history_list.append({"role": content.role, "parts": parts})
        
        conn = sqlite3.connect("orders.db")
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO chat_history (sender_id, history) VALUES (?, ?)", 
                  (sender_id, json.dumps(history_list)))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Failed to save history:", e)

def load_history(sender_id):
    try:
        conn = sqlite3.connect("orders.db")
        c = conn.cursor()
        c.execute("SELECT history FROM chat_history WHERE sender_id = ?", (sender_id,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return json.loads(row[0])
    except Exception as e:
        print("Failed to load history:", e)
    return []

# 1. System Instructions (Persona)
system_instruction = """তুমি হচ্ছো 'কারুশিল্প' (Karushilpo) নামের একটি ফেসবুক পেইজের কাস্টমার সার্ভিস অ্যাসিস্ট্যান্ট।
'কারুশিল্প' পেইজে সকল প্রকার হাতের কাজ করা (Handicrafts) চমৎকার জিনিসপত্র বিক্রি করা হয়। 
তোমার দায়িত্ব হলো কাস্টমারদের সাথে অত্যন্ত নম্র, ভদ্র ও বন্ধুত্বপূর্ণ ভাষায় বাংলায় কথা বলা। কাস্টমারদের যেকোনো প্রশ্নের উত্তর দেওয়া এবং তাদের প্রোডাক্ট কিনতে সাহায্য করা।

**স্টক ম্যানেজমেন্ট রুলস:**
তোমার কাছে সব সময় বর্তমান স্টকের একটি লাইভ তালিকা থাকবে। কাস্টমার কোনো প্রোডাক্ট চাইলে তুমি সাথে সাথে লিস্ট চেক করে দেখবে সেটি স্টকে আছে কি না। 
স্টকে থাকলে দাম জানাবে, আর স্টক আউট হয়ে গেলে ভদ্রভাবে বলবে যে প্রোডাক্টটি আপাতত শেষ।

কাস্টমার কোনো প্রোডাক্টের দাম জানতে চাইলে বলবে যে, ডিজাইন ও সুতার কাজের ওপর ভিত্তি করে দাম নির্ভর করে, তাই কাস্টমারকে তাদের পছন্দের ডিজাইন বা ছবি ইনবক্সে দিতে বলবে।
কাস্টমার যদি কোনো ছবি পাঠায়, তুমি সেটি ভালোভাবে দেখে কাস্টমারকে বলবে যে এটি একটি দারুণ ডিজাইন এবং আমরা এ ধরনের কাজ করে দিতে পারব।
কেউ যদি ডেলিভারি সম্পর্কে জানতে চায়, বলবে: "আমরা সারা বাংলাদেশে কুরিয়ারের মাধ্যমে খুব যত্ন সহকারে হোম ডেলিভারি দিয়ে থাকি।"
কেউ যদি অ্যাডমিনের সাথে কথা বলতে চায়, বলবে: "অবশ্যই! আমাদের অ্যাডমিন কিছুক্ষণের মধ্যেই আপনার সাথে যুক্ত হবেন। অনুগ্রহ করে একটু অপেক্ষা করুন।"

**অর্ডার নেওয়ার নিয়ম:**
যদি কাস্টমার কোনো প্রোডাক্ট অর্ডার করতে চায়, তবে তার কাছ থেকে এই ৪টি তথ্য অবশ্যই জেনে নিবে: ১. নাম, ২. ফোন নাম্বার, ৩. সম্পূর্ণ ঠিকানা এবং ৪. প্রোডাক্টের নাম/বিস্তারিত।
যখন কাস্টমার এই ৪টি তথ্য দিয়ে দিবে, তখন তুমি তোমার উত্তরের একদম শেষে ঠিক এইভাবে একটি JSON ব্লক যুক্ত করে দিবে:
```json
{
  "order_confirmed": true,
  "name": "কাস্টমারের নাম",
  "phone": "ফোন নাম্বার",
  "address": "ঠিকানা",
  "product": "প্রোডাক্টের নাম"
}
```
তুমি এই JSON ব্লকটি ছাড়া অন্য কোনো সময় JSON ব্যবহার করবে না।

তোমার উত্তরগুলো হবে খুব স্মার্ট, গুছানো এবং যতটা সম্ভব ছোট (খুব বেশি বড় প্যারাগ্রাফ লিখবে না)। ইমোজি ব্যবহার করতে পারো।"""

# 3. Paused Users (Human Handoff state)
paused_users = set()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ULTRAMSG_INSTANCE_ID = os.getenv("ULTRAMSG_INSTANCE_ID")
ULTRAMSG_TOKEN = os.getenv("ULTRAMSG_TOKEN")
ADMIN_WHATSAPP_NUMBER = os.getenv("ADMIN_WHATSAPP_NUMBER")

def send_telegram_notification(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def send_whatsapp_notification(text):
    if not ULTRAMSG_INSTANCE_ID or not ULTRAMSG_TOKEN or not ADMIN_WHATSAPP_NUMBER:
        return
    url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE_ID}/messages/chat"
    payload = {
        "token": ULTRAMSG_TOKEN,
        "to": ADMIN_WHATSAPP_NUMBER,
        "body": text
    }
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    try:
        requests.post(url, data=payload, headers=headers)
    except Exception as e:
        print(f"WhatsApp Error: {e}")

@app.route("/", methods=["GET"])
def home():
    return "Facebook AI Agent running."

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

def process_message(sender_id, user_message, image_urls, audio_urls=None):
    """Background task to get AI response and send it to avoid timeout."""
    ai_response_text = get_ai_response(sender_id, user_message, image_urls, audio_urls)
    send_message(sender_id, ai_response_text)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event.get("sender", {}).get("id")
                recipient_id = messaging_event.get("recipient", {}).get("id")
                message = messaging_event.get("message", {})
                
                # 1. Handle Admin Echo Messages (Admin taking over or resuming)
                if message.get("is_echo"):
                    user_id = recipient_id
                    admin_text = message.get("text", "").strip()
                    
                    if admin_text.lower() == "/resume":
                        if user_id in paused_users:
                            paused_users.remove(user_id)
                            send_message(user_id, "অ্যাডমিন চ্যাট থেকে বিদায় নিয়েছেন। আমি (এআই অ্যাসিস্ট্যান্ট) আবারও যুক্ত হয়েছি! আপনাকে কীভাবে সাহায্য করতে পারি?")
                            send_telegram_notification(f"✅ এআই অ্যাসিস্ট্যান্ট আবার চালু করা হয়েছে। (Customer ID: {user_id})")
                            send_whatsapp_notification(f"✅ এআই অ্যাসিস্ট্যান্ট আবার চালু করা হয়েছে। (Customer ID: {user_id})")
                    continue
                
                user_id = sender_id
                
                # 2. If the bot is paused for this user, ignore their messages (Admin is talking)
                if user_id in paused_users:
                    continue
                
                user_message = message.get("text", "")
                quick_reply = message.get("quick_reply", {})
                payload = quick_reply.get("payload", "")
                
                # 3. Check for Human Handoff trigger
                if payload == "TALK_TO_ADMIN" or "অ্যাডমিন" in user_message:
                    paused_users.add(user_id)
                    send_message(user_id, "অবশ্যই! আমি আমার অটো-রিপ্লাই সাময়িকভাবে বন্ধ করছি। আমাদের অ্যাডমিন কিছুক্ষণের মধ্যেই আপনার মেসেজের রিপ্লাই দিবেন। একটু অপেক্ষা করুন।")
                    
                    # Notify Admin via Telegram and WhatsApp
                    alert_msg = f"🚨 অ্যালার্ট! ফেসবুক পেইজে একজন কাস্টমার আপনার সাথে কথা বলতে চাচ্ছেন।\nCustomer ID: {user_id}\nদয়া করে Facebook Inbox চেক করুন।"
                    threading.Thread(target=send_telegram_notification, args=(alert_msg,)).start()
                    threading.Thread(target=send_whatsapp_notification, args=(alert_msg,)).start()
                    continue
                
                image_urls = []
                audio_urls = []
                
                # Check for image and audio attachments
                if "attachments" in message:
                    for attachment in message["attachments"]:
                        if attachment.get("type") == "image":
                            image_urls.append(attachment["payload"]["url"])
                        elif attachment.get("type") == "audio" or attachment.get("type") == "video":
                            audio_urls.append(attachment["payload"]["url"])
                
                if user_message or image_urls or audio_urls:
                    print(f"Received from {user_id}: Text: '{user_message}', Images: {len(image_urls)}, Audio: {len(audio_urls)}")
                    
                    # Run AI and messaging tasks in a background thread
                    thread = threading.Thread(target=process_message, args=(user_id, user_message, image_urls, audio_urls))
                    thread.start()
                    
    # Return 200 OK immediately so Facebook stops retrying
    return "EVENT_RECEIVED", 200

@app.route("/invoice/<int:order_id>")
def view_invoice(order_id):
    from flask import render_template_string
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("SELECT customer_name, phone, address, product, status, payment_status FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    conn.close()
    
    if not order:
        return "Invoice not found", 404
        
    html = """
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Invoice #{{ order_id }}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;600;700&display=swap');
            body { font-family: 'Hind Siliguri', sans-serif; }
        </style>
    </head>
    <body class="bg-gray-100 p-4 md:p-8">
        <div id="invoice-content" class="max-w-2xl mx-auto bg-white p-8 rounded-lg shadow-lg mt-4">
            <div class="flex justify-between items-center border-b pb-6">
                <div>
                    <h1 class="text-4xl font-bold text-blue-600">কারুশিল্প</h1>
                    <p class="text-gray-500 mt-1">Handicrafts & Boutique</p>
                </div>
                <div class="text-right">
                    <h2 class="text-2xl font-bold text-gray-700">INVOICE</h2>
                    <p class="text-gray-500">Order #{{ order_id }}</p>
                    <p class="text-sm font-semibold text-blue-600 mt-1 bg-blue-100 inline-block px-2 py-1 rounded">{{ status }}</p>
                    {% if payment_status == 'Paid' %}
                    <p class="text-sm font-bold text-green-700 mt-1 bg-green-100 inline-block px-2 py-1 rounded">✅ PAID</p>
                    {% else %}
                    <p class="text-sm font-bold text-red-600 mt-1 bg-red-100 inline-block px-2 py-1 rounded">❌ UNPAID</p>
                    {% endif %}
                </div>
            </div>
            
            <div class="mt-8">
                <h3 class="text-lg font-bold text-gray-700 border-b pb-2">Customer Details</h3>
                <div class="mt-4 grid grid-cols-2 gap-4">
                    <div>
                        <p class="text-sm text-gray-500">Name:</p>
                        <p class="font-semibold text-gray-800 text-lg">{{ order[0] }}</p>
                    </div>
                    <div>
                        <p class="text-sm text-gray-500">Phone:</p>
                        <p class="font-semibold text-gray-800 text-lg">{{ order[1] }}</p>
                    </div>
                    <div class="col-span-2">
                        <p class="text-sm text-gray-500">Delivery Address:</p>
                        <p class="font-semibold text-gray-800">{{ order[2] }}</p>
                    </div>
                </div>
            </div>
            
            <div class="mt-8">
                <h3 class="text-lg font-bold text-gray-700 border-b pb-2">Order Details</h3>
                <table class="w-full mt-4 text-left border-collapse">
                    <thead>
                        <tr class="bg-gray-100 text-gray-600 text-sm uppercase">
                            <th class="p-3 border">Product Description</th>
                            <th class="p-3 border w-24 text-center">Qty</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr class="border-b">
                            <td class="p-3 border text-gray-800">{{ order[3] }}</td>
                            <td class="p-3 border text-center font-bold">1</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div class="mt-12 text-center text-gray-500 text-sm">
                <p class="text-lg text-gray-700 font-semibold">আমাদের সাথে কেনাকাটা করার জন্য ধন্যবাদ!</p>
                <p>Thank you for shopping with Karushilpo.</p>
            </div>
        </div>
        
        <div class="text-center mt-6 flex justify-center gap-4">
            <button onclick="downloadPDF()" id="download-btn" class="px-6 py-2 bg-gray-600 text-white rounded-lg shadow hover:bg-gray-700 transition">
                ⬇️ Download PDF
            </button>
            {% if payment_status != 'Paid' %}
            <a href="/payment/checkout/{{ order_id }}" class="px-6 py-2 bg-pink-600 text-white rounded-lg shadow hover:bg-pink-700 transition font-bold">
                💳 Pay Now
            </a>
            {% endif %}
        </div>

        <script>
            function downloadPDF() {
                var btn = document.getElementById('download-btn');
                btn.innerHTML = '⏳ Downloading...';
                
                var element = document.getElementById('invoice-content');
                var opt = {
                  margin:       0.5,
                  filename:     'Karushilpo_Invoice_{{ order_id }}.pdf',
                  image:        { type: 'jpeg', quality: 0.98 },
                  html2canvas:  { scale: 2 },
                  jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
                };
                
                html2pdf().set(opt).from(element).save().then(function() {
                    btn.innerHTML = '✅ Downloaded!';
                    setTimeout(function() { btn.innerHTML = '⬇️ Download PDF'; }, 3000);
                });
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, order_id=order_id, order=order, status=order[4], payment_status=order[5])

from flask import render_template_string, Response
from functools import wraps

# --- Authentication Logic ---
def check_auth(username, password):
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASS", "admin123")
    return username == admin_user and password == admin_pass

def authenticate():
    return Response(
    'Please login to access the admin panel.', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# --- Unified Admin Dashboard Route ---
@app.route("/admin", methods=["GET", "POST"])
@requires_auth
def admin_dashboard():
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    
    # Handle all form submissions (Orders and Products)
    if request.method == "POST":
        action = request.form.get("action")
        
        # 1. Update Order Status
        if action == "update_order":
            order_id = request.form.get("order_id")
            new_status = request.form.get("status")
            if order_id and new_status:
                c.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        
        # 2. Add New Product
        elif action == "add_product":
            name = request.form.get("name")
            price = request.form.get("price")
            stock = request.form.get("stock")
            if name and price and stock:
                c.execute("INSERT INTO products (name, price, stock_quantity) VALUES (?, ?, ?)", (name, price, int(stock)))
        
        # 3. Update Product Stock
        elif action == "update_product":
            p_id = request.form.get("product_id")
            stock = request.form.get("stock")
            if p_id and stock:
                c.execute("UPDATE products SET stock_quantity = ? WHERE id = ?", (int(stock), p_id))
        
        # 4. Delete Product
        elif action == "delete_product":
            p_id = request.form.get("product_id")
            if p_id:
                c.execute("DELETE FROM products WHERE id = ?", (p_id,))
                
        conn.commit()

    # Fetch Data
    c.execute("SELECT COUNT(*) FROM chat_history")
    total_customers = c.fetchone()[0]
    
    c.execute("SELECT id, customer_name, phone, product, status, payment_status FROM orders ORDER BY id DESC")
    orders = c.fetchall()
    
    c.execute("SELECT id, name, price, stock_quantity FROM products ORDER BY id DESC")
    products = c.fetchall()
    conn.close()
    
    html = """
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <title>Admin Dashboard - Karushilpo</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;600;700&display=swap');
            body { font-family: 'Hind Siliguri', sans-serif; }
        </style>
    </head>
    <body class="bg-gray-100 p-4 md:p-8">
        <div class="max-w-7xl mx-auto">
            <!-- Header -->
            <div class="flex flex-col md:flex-row justify-between items-center mb-8 bg-white p-6 rounded-lg shadow">
                <h1 class="text-3xl font-bold text-blue-800">⚙️ Karushilpo Admin Panel</h1>
                <div class="mt-4 md:mt-0">
                    <a href="/broadcast" class="bg-purple-600 text-white px-6 py-3 rounded-lg shadow font-bold hover:bg-purple-700 transition">📢 Go to Broadcast</a>
                </div>
            </div>
            
            <!-- Quick Stats -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="bg-white p-6 rounded-lg shadow border-l-4 border-blue-500">
                    <h3 class="text-gray-500 text-sm font-bold uppercase">Total Orders</h3>
                    <p class="text-3xl font-bold text-gray-800">{{ orders|length }}</p>
                </div>
                <div class="bg-white p-6 rounded-lg shadow border-l-4 border-green-500">
                    <h3 class="text-gray-500 text-sm font-bold uppercase">Total Customers</h3>
                    <p class="text-3xl font-bold text-gray-800">{{ total_customers }}</p>
                </div>
                <div class="bg-white p-6 rounded-lg shadow border-l-4 border-indigo-500">
                    <h3 class="text-gray-500 text-sm font-bold uppercase">Total Products</h3>
                    <p class="text-3xl font-bold text-gray-800">{{ products|length }}</p>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                
                <!-- LEFT COLUMN: Live Stock Manager -->
                <div>
                    <!-- Add Product Form -->
                    <div class="bg-white p-6 rounded-lg shadow mb-6 border-t-4 border-indigo-500">
                        <h2 class="text-xl font-bold text-gray-800 mb-4">➕ Add New Product</h2>
                        <form method="POST" class="flex flex-col gap-4">
                            <input type="hidden" name="action" value="add_product">
                            <div>
                                <label class="block text-sm text-gray-600 font-bold mb-1">Product Name</label>
                                <input type="text" name="name" class="w-full border rounded p-2 focus:outline-none focus:ring-2 focus:ring-indigo-500" required placeholder="যেমন: নীল সুতির থ্রি-পিস">
                            </div>
                            <div class="flex gap-4">
                                <div class="flex-1">
                                    <label class="block text-sm text-gray-600 font-bold mb-1">Price (৳)</label>
                                    <input type="number" name="price" class="w-full border rounded p-2 focus:outline-none focus:ring-2 focus:ring-indigo-500" required placeholder="1500">
                                </div>
                                <div class="flex-1">
                                    <label class="block text-sm text-gray-600 font-bold mb-1">Stock Qty</label>
                                    <input type="number" name="stock" class="w-full border rounded p-2 focus:outline-none focus:ring-2 focus:ring-indigo-500" required placeholder="10">
                                </div>
                            </div>
                            <button type="submit" class="bg-indigo-600 text-white py-2 rounded-lg font-bold hover:bg-indigo-700 w-full mt-2">Add to Stock</button>
                        </form>
                    </div>

                    <!-- Product List -->
                    <div class="bg-white rounded-lg shadow overflow-hidden">
                        <div class="bg-gray-50 p-4 border-b">
                            <h2 class="text-lg font-bold text-gray-800">📦 Available Stock</h2>
                        </div>
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-gray-100 text-gray-600 text-xs uppercase">
                                    <th class="p-3 border-b">Product</th>
                                    <th class="p-3 border-b">Stock</th>
                                    <th class="p-3 border-b text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for p in products %}
                                <tr class="border-b hover:bg-gray-50">
                                    <td class="p-3">
                                        <p class="font-bold text-gray-800 text-sm">{{ p[1] }}</p>
                                        <p class="text-xs text-green-600 font-bold">৳ {{ p[2] }}</p>
                                    </td>
                                    <td class="p-3">
                                        <form method="POST" class="flex gap-1">
                                            <input type="hidden" name="action" value="update_product">
                                            <input type="hidden" name="product_id" value="{{ p[0] }}">
                                            <input type="number" name="stock" value="{{ p[3] }}" class="border rounded p-1 w-16 text-center text-sm font-bold {% if p[3] == 0 %}text-red-500{% endif %}">
                                            <button type="submit" class="bg-blue-500 text-white px-2 py-1 rounded text-xs hover:bg-blue-600">Up</button>
                                        </form>
                                    </td>
                                    <td class="p-3 text-right">
                                        <form method="POST" onsubmit="return confirm('Delete product?');">
                                            <input type="hidden" name="action" value="delete_product">
                                            <input type="hidden" name="product_id" value="{{ p[0] }}">
                                            <button type="submit" class="text-red-500 hover:text-red-700 text-sm font-bold">Delete</button>
                                        </form>
                                    </td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                        {% if not products %}
                        <div class="p-8 text-center text-gray-500 text-sm">No products added yet.</div>
                        {% endif %}
                    </div>
                </div>

                <!-- RIGHT COLUMN: Orders List -->
                <div>
                    <div class="bg-white rounded-lg shadow overflow-hidden border-t-4 border-blue-500">
                        <div class="bg-gray-50 p-4 border-b flex justify-between items-center">
                            <h2 class="text-xl font-bold text-gray-800">🛍️ Recent Orders</h2>
                        </div>
                        <div class="overflow-x-auto">
                            <table class="w-full text-left border-collapse">
                                <thead>
                                    <tr class="bg-gray-100 text-gray-600 text-xs uppercase">
                                        <th class="p-3 border-b">ID</th>
                                        <th class="p-3 border-b">Customer</th>
                                        <th class="p-3 border-b">Payment</th>
                                        <th class="p-3 border-b">Status & Action</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for order in orders %}
                                    <tr class="border-b hover:bg-gray-50">
                                        <td class="p-3 font-bold text-blue-600">#{{ order[0] }}</td>
                                        <td class="p-3">
                                            <p class="font-bold text-gray-800 text-sm">{{ order[1] }}</p>
                                            <p class="text-xs text-gray-500 line-clamp-1" title="{{ order[3] }}">{{ order[3] }}</p>
                                        </td>
                                        <td class="p-3">
                                            {% if order[5] == 'Paid' %}
                                            <span class="bg-green-100 text-green-800 text-xs font-bold px-2 py-1 rounded">Paid</span>
                                            {% else %}
                                            <span class="bg-red-100 text-red-800 text-xs font-bold px-2 py-1 rounded">Unpaid</span>
                                            {% endif %}
                                        </td>
                                        <td class="p-3">
                                            <form method="POST" class="flex flex-col gap-1">
                                                <input type="hidden" name="action" value="update_order">
                                                <input type="hidden" name="order_id" value="{{ order[0] }}">
                                                <select name="status" class="border rounded p-1 text-xs font-bold w-28 bg-white focus:outline-none 
                                                    {% if order[4] == 'Pending' %}text-yellow-600
                                                    {% elif order[4] == 'Processing' %}text-blue-600
                                                    {% else %}text-green-600{% endif %}">
                                                    <option value="Pending" {% if order[4] == 'Pending' %}selected{% endif %}>Pending</option>
                                                    <option value="Processing" {% if order[4] == 'Processing' %}selected{% endif %}>Processing</option>
                                                    <option value="Delivered" {% if order[4] == 'Delivered' %}selected{% endif %}>Delivered</option>
                                                </select>
                                                <button type="submit" class="bg-blue-600 text-white px-2 py-1 rounded text-xs hover:bg-blue-700 w-28">Update</button>
                                            </form>
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                        {% if not orders %}
                        <div class="p-8 text-center text-gray-500 text-sm">No orders found yet.</div>
                        {% endif %}
                    </div>
                </div>

            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, orders=orders, total_customers=total_customers, products=products)

@app.route("/broadcast", methods=["GET", "POST"])
@requires_auth
def broadcast():
    from flask import render_template_string
    
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT sender_id FROM chat_history")
    customers = c.fetchall()
    conn.close()
    
    total_customers = len(customers)
    
    if request.method == "POST":
        message = request.form.get("message")
        if message:
            def send_broadcast(msg, customer_list):
                success_count = 0
                for cust in customer_list:
                    # cust[0] is the sender_id
                    send_message(cust[0], msg)
                    success_count += 1
                    # 1 second delay to avoid Facebook rate limit spam
                    time.sleep(1) 
                
                # Notify admin when done
                alert = f"📢 ব্রডকাস্ট সম্পন্ন হয়েছে!\nমোট {success_count} জন কাস্টমারকে অফার মেসেজ পাঠানো হয়েছে।"
                send_telegram_notification(alert)
                send_whatsapp_notification(alert)

            # Start sending in background
            threading.Thread(target=send_broadcast, args=(message, customers)).start()
            
            success_html = f"""
            <div style="font-family: sans-serif; text-align: center; margin-top: 50px;">
                <h2 style="color: green;">✅ ব্রডকাস্ট শুরু হয়েছে!</h2>
                <p>ব্যাকগ্রাউন্ডে <b>{total_customers}</b> জন কাস্টমারকে মেসেজ পাঠানো হচ্ছে। শেষ হলে আপনার নাম্বারে নোটিফিকেশন দেওয়া হবে।</p>
                <a href="/broadcast" style="display: inline-block; margin-top: 20px; padding: 10px 20px; background: blue; color: white; text-decoration: none; border-radius: 5px;">Back to Broadcast</a>
            </div>
            """
            return success_html

    html = """
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Broadcast Message - Karushilpo</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;600;700&display=swap');
            body { font-family: 'Hind Siliguri', sans-serif; }
        </style>
    </head>
    <body class="bg-gray-100 p-4 md:p-8">
        <div class="max-w-xl mx-auto bg-white p-8 rounded-lg shadow-lg mt-10 border-t-4 border-blue-600">
            <h1 class="text-3xl font-bold text-blue-600 mb-2">📢 প্রমোশনাল ব্রডকাস্ট</h1>
            <p class="text-gray-600 mb-6">আপনার ডাটাবেসে মোট <strong class="text-green-600 text-lg">{{ total }}</strong> জন কাস্টমার আছে, যারা আগে আপনার পেইজে মেসেজ দিয়েছিল।</p>
            
            <form method="POST">
                <label class="block text-gray-700 font-bold mb-2">আপনার মেসেজ বা অফার লিখুন:</label>
                <textarea name="message" rows="5" class="w-full p-4 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 mb-6" placeholder="যেমন: ঈদ ধামাকা! সকল থ্রি-পিসে ৫০% ছাড়! আজই অর্ডার করুন..." required></textarea>
                
                <button type="submit" class="w-full bg-blue-600 text-white font-bold py-3 rounded-lg shadow-md hover:bg-blue-700 transition">
                    🚀 Send to {{ total }} Customers
                </button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, total=total_customers)

def get_ai_response(sender_id, text, image_urls, audio_urls=None):
    try:
        # 1. Fetch live stock from database
        conn = sqlite3.connect("orders.db")
        c = conn.cursor()
        c.execute("SELECT name, price, stock_quantity FROM products")
        products = c.fetchall()
        conn.close()
        
        # 2. Build Dynamic Stock Context
        stock_info = "\n\n[অ্যাডমিন প্যানেল থেকে লাইভ স্টক আপডেট:]\nবর্তমানে আমাদের ডাটাবেসে নিচের প্রোডাক্টগুলো আছে:\n"
        if products:
            for p in products:
                status = f"স্টকে আছে (Quantity: {p[2]})" if p[2] > 0 else "স্টক আউট (শেষ)"
                stock_info += f"- {p[0]}: দাম {p[1]} টাকা, অবস্থা: {status}\n"
        else:
            stock_info += "বর্তমানে ডাটাবেসে কোনো প্রোডাক্ট নেই।\n"
            
        dynamic_instruction = system_instruction + stock_info
        
        # 3. Initialize model with dynamic live stock
        live_model = genai.GenerativeModel('gemini-3.8-flash', system_instruction=dynamic_instruction)

        # 4. Load past history and start chat directly (stateless, no user_sessions dict needed)
        past_history = load_history(sender_id)
        chat = live_model.start_chat(history=past_history)
        
        # Prepare the message content (Text + Images)
        message_parts = []
        if text:
            message_parts.append(text)
        
        # Process images
        for url in image_urls:
            img_response = requests.get(url)
            if img_response.status_code == 200:
                img = Image.open(BytesIO(img_response.content))
                message_parts.append(img)
                
        # Process audio (Inline Data)
        if audio_urls:
            for url in audio_urls:
                audio_resp = requests.get(url)
                if audio_resp.status_code == 200:
                    # Pass as inline data to bypass discovery API limitations
                    message_parts.append({
                        "mime_type": "audio/mp4",
                        "data": audio_resp.content
                    })
        
        if not text and image_urls and not audio_urls:
            message_parts.append("এই ছবিটি দেখে বলো এই ডিজাইনটি কেমন এবং 'কারুশিল্প' পেইজের হাতের কাজের সাথে এটি কীভাবে মিলে যায়।")
        if not text and audio_urls and not image_urls:
            message_parts.append("কাস্টমার একটি ভয়েস মেসেজ পাঠিয়েছে। অডিওটি শুনে কাস্টমারের কথার সুন্দরভাবে বাংলায় উত্তর দাও।")
            
        if not message_parts:
            return "আমি আপনার মেসেজটি বুঝতে পারিনি।"

        # Send message to Gemini and get response
        response = chat.send_message(message_parts)
        response_text = response.text
        

        
        # After sending message, save the updated history to DB
        save_history(sender_id, chat)
        
        # Check for JSON order block
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            try:
                order_data = json.loads(json_match.group(1))
                if order_data.get("order_confirmed"):
                    name = order_data.get("name", "")
                    phone = order_data.get("phone", "")
                    address = order_data.get("address", "")
                    product = order_data.get("product", "")
                    
                    # Save to DB
                    conn = sqlite3.connect("orders.db")
                    c = conn.cursor()
                    c.execute("INSERT INTO orders (sender_id, customer_name, phone, address, product) VALUES (?, ?, ?, ?, ?)",
                              (sender_id, name, phone, address, product))
                    order_id = c.lastrowid
                    conn.commit()
                    conn.close()
                    
                    invoice_url = f"https://ai.engrshamim.shop/invoice/{order_id}"
                    
                    # Replace JSON block with a friendly message + Invoice Link
                    success_msg = f'\n\n🎉 আপনার অর্ডারটি সফলভাবে আমাদের সিস্টেমে সেভ করা হয়েছে!\n\nআপনার ডিজিটাল ইনভয়েস দেখতে বা ডাউনলোড করতে নিচের লিংকে ক্লিক করুন:\n👉 {invoice_url}\n\nখুব দ্রুত আমাদের প্রতিনিধি আপনার দেওয়া নাম্বারে যোগাযোগ করবেন।'
                    response_text = re.sub(r'```json\s*\{.*?\}\s*```', success_msg, response_text, flags=re.DOTALL)
                    
                    # Alert Admin
                    alert_msg = f"🛍️ 🎉 নতুন অর্ডার এসেছে!\n\nনাম: {name}\nফোন: {phone}\nঠিকানা: {address}\nপ্রোডাক্ট: {product}\nInvoice: {invoice_url}\nCustomer ID: {sender_id}"
                    threading.Thread(target=send_telegram_notification, args=(alert_msg,)).start()
                    threading.Thread(target=send_whatsapp_notification, args=(alert_msg,)).start()
            except Exception as e:
                print("Failed to parse order JSON:", e)

        return response_text
    except Exception as e:
        print(f"AI Error: {e}")
        return "দুঃখিত, আমি এই মুহূর্তে উত্তর দিতে পারছি না। অনুগ্রহ করে একটু পর আবার মেসেজ দিন।"

def send_message(recipient_id, text):
    url = f"https://graph.facebook.com/v20.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    
    # Quick Replies (Buttons)
    quick_replies = [
        {
            "content_type": "text",
            "title": "থ্রি-পিস কালেকশন",
            "payload": "THREE_PIECE"
        },
        {
            "content_type": "text",
            "title": "ডেলিভারি চার্জ",
            "payload": "DELIVERY_INFO"
        },
        {
            "content_type": "text",
            "title": "অ্যাডমিনের সাথে কথা",
            "payload": "TALK_TO_ADMIN"
        }
    ]

    payload = {
        "messaging_type": "RESPONSE",
        "recipient": {"id": recipient_id},
        "message": {
            "text": text,
            "quick_replies": quick_replies
        }
    }
    headers = {"Content-Type": "application/json"}
    
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        print("Message sent successfully!")
    else:
        print(f"Failed to send message: {response.text}")


# --- Mock Payment Gateway ---
@app.route("/payment/checkout/<int:order_id>")
def payment_checkout(order_id):
    from flask import render_template_string
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("SELECT customer_name, product, payment_status FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    conn.close()
    
    if not order:
        return "Order not found", 404
    if order[2] == 'Paid':
        return "This order is already paid."

    html = """
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <title>Secure Payment Gateway</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;600;700&display=swap');
            body { font-family: 'Hind Siliguri', sans-serif; background-color: #f4f7f6; }
        </style>
    </head>
    <body class="flex items-center justify-center min-h-screen">
        <div class="bg-white p-8 rounded-xl shadow-2xl max-w-md w-full border-t-4 border-pink-500 text-center">
            <img src="https://www.logo.wine/a/logo/BKash/BKash-Icon-Logo.wine.svg" alt="bKash" class="h-16 mx-auto mb-4">
            <h2 class="text-2xl font-bold text-gray-800">Secure Payment Checkout</h2>
            <p class="text-gray-500 mb-6">Order #{{ order_id }} | {{ order[0] }}</p>
            
            <div class="bg-gray-100 p-4 rounded-lg mb-6 text-left">
                <p class="text-sm text-gray-600">You are paying for:</p>
                <p class="font-bold text-gray-800">{{ order[1] }}</p>
            </div>
            
            <form action="/payment/success/{{ order_id }}" method="POST">
                <div class="mb-4 text-left">
                    <label class="block text-sm font-bold text-gray-700 mb-2">bKash Account Number</label>
                    <input type="text" placeholder="01XXXXXXXXX" class="w-full border p-3 rounded bg-gray-50 focus:ring-2 focus:ring-pink-500 focus:outline-none" required>
                </div>
                <div class="mb-6 text-left">
                    <label class="block text-sm font-bold text-gray-700 mb-2">PIN</label>
                    <input type="password" placeholder="••••" class="w-full border p-3 rounded bg-gray-50 focus:ring-2 focus:ring-pink-500 focus:outline-none" required>
                </div>
                <button type="submit" class="w-full bg-pink-600 text-white font-bold py-3 rounded-lg hover:bg-pink-700 transition shadow-lg">Confirm Payment</button>
            </form>
            <p class="text-xs text-gray-400 mt-4">This is a simulated Sandbox gateway.</p>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, order_id=order_id, order=order)

@app.route("/payment/success/<int:order_id>", methods=["POST"])
def payment_success(order_id):
    conn = sqlite3.connect("orders.db")
    c = conn.cursor()
    c.execute("UPDATE orders SET payment_status = 'Paid' WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    
    # Redirect back to invoice
    from flask import redirect
    return redirect(f"/invoice/{order_id}")

if __name__ == "__main__":
    app.run(port=8080)

