import os, sqlite3, requests, base64
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from groq import Groq

# 1. KONFIGURASI
load_dotenv()

# Penyesuaian path folder agar Flask menemukan template/static saat di Vercel
app = Flask(__name__, 
            template_folder='../templates', 
            static_folder='../static')

app.secret_key = os.getenv("FLASK_SECRET_KEY", "kord_pxl_core_secure_992026_final")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# --- KONFIGURASI DATABASE UNTUK VERCEL ---
# Jika berjalan di Vercel, pindahkan DB ke folder /tmp (area yang bisa ditulis)
if os.environ.get('VERCEL'):
    DB_NAME = "/tmp/kordbio.db"
else:
    DB_NAME = "kordbio.db"

def get_db():
    # Inisialisasi DB jika belum ada di folder /tmp
    if not os.path.exists(DB_NAME):
        init_db()
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with sqlite3.connect(DB_NAME) as db:
        # Tabel Utama (Kode asli kamu tetap sama)
        db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            username TEXT UNIQUE, 
            password_hash TEXT, 
            bio TEXT DEFAULT 'Creative Developer', 
            lang TEXT DEFAULT 'id', 
            theme TEXT DEFAULT 'dark',
            is_premium INTEGER DEFAULT 0,
            custom_prefix TEXT DEFAULT '>>',
            profile_glow TEXT DEFAULT '#22c55e')''')
            
        db.execute('''CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
            content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            
        db.execute('''CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
            title TEXT, description TEXT, link TEXT)''')
            
        db.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER, receiver_id INTEGER, 
            message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, is_read INTEGER DEFAULT 0)''')
        
        db.execute('''CREATE TABLE IF NOT EXISTS ai_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

        db.execute('''CREATE TABLE IF NOT EXISTS confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tier INTEGER,
            proof_image TEXT, 
            status TEXT DEFAULT 'PENDING', 
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        db.commit()

# Pastikan DB siap saat aplikasi menyala
init_db()

def current_user():
    if 'user_id' in session:
        db = get_db()
        return db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    return None

@app.context_processor
def inject_notifications():
    user = current_user()
    unread_count = 0
    ai_count = 0
    if user:
        db = get_db()
        today = datetime.now().strftime('%Y-%m-%d')
        res_m = db.execute("SELECT COUNT(*) as count FROM messages WHERE receiver_id=? AND is_read=0", (user['id'],)).fetchone()
        unread_count = res_m['count'] if res_m else 0
        res_a = db.execute("SELECT COUNT(*) as count FROM ai_logs WHERE user_id=? AND date(timestamp) = ?", 
                           (user['id'], today)).fetchone()
        ai_count = res_a['count'] if res_a else 0
        
    return dict(user=user, unread_count=unread_count, ai_count=ai_count, now=datetime.now().strftime('%Y-%m-%d %H:%M'))

# --- 1. AUTH ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE username=?", (request.form['username'].lower().strip(),)).fetchone()
        if u and check_password_hash(u['password_hash'], request.form['password']):
            session['user_id'] = u['id']
            flash("ACCESS_GRANTED: Welcome back.", "success")
            return redirect(url_for('dashboard'))
        flash("ACCESS_DENIED: Invalid credentials.", "error")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        db = get_db()
        username = request.form['username'].lower().strip()
        reserved = ['login', 'register', 'dashboard', 'settings', 'logout', 'manage', 'api', 'chat', 'messages', 'upgrade', 'admin', 'webhook']
        if username in reserved:
            flash("SYSTEM_ERROR: Username reserved.", "error")
            return redirect(url_for('register'))
        try:
            db.execute("INSERT INTO users (username, password_hash) VALUES (?,?)", 
                       (username, generate_password_hash(request.form['password'])))
            db.commit()
            flash("USER_CREATED: Welcome to the grid.", "success")
            return redirect(url_for('login'))
        except: 
            flash("SYSTEM_ERROR: Username already exists.", "error")
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("SESSION_TERMINATED.", "warning")
    return redirect(url_for('index'))

# --- 2. ACTION ROUTES ---

@app.route('/manage/create-post', methods=['POST'])
def action_create_post():
    user = current_user()
    if not user: return redirect(url_for('login'))
    content = request.form.get('content', '').strip()
    if content:
        db = get_db()
        db.execute("INSERT INTO posts (user_id, content) VALUES (?,?)", (user['id'], content))
        db.commit()
        flash("LOG_ENTRY_SUCCESS.", "success")
    return redirect(url_for('index'))

@app.route('/manage/delete-post/<int:id>')
def action_delete_post(id):
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    db.execute("DELETE FROM posts WHERE id=? AND user_id=?", (id, user['id']))
    db.commit()
    flash("DATA_ERASED.", "warning")
    return redirect(url_for('index'))

@app.route('/manage/delete-project/<int:id>')
def action_delete_project(id):
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    db.execute("DELETE FROM projects WHERE id=? AND user_id=?", (id, user['id']))
    db.commit()
    flash("PROJECT_WIPED.", "warning")
    return redirect(url_for('dashboard'))

@app.route('/manage/self-destruct', methods=['GET', 'POST'])
def action_self_destruct():
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    db.execute("DELETE FROM projects WHERE user_id=?", (user['id'],))
    db.execute("DELETE FROM posts WHERE user_id=?", (user['id'],))
    db.execute("DELETE FROM messages WHERE sender_id=? OR receiver_id=?", (user['id'], user['id']))
    db.execute("DELETE FROM ai_logs WHERE user_id=?", (user['id'],))
    db.execute("DELETE FROM users WHERE id=?", (user['id'],))
    db.commit()
    session.clear()
    flash("ACCOUNT_TERMINATED: All data wiped.", "error")
    return redirect(url_for('index'))

@app.route('/manage/delete-chat/<int:target_id>', methods=['GET', 'POST'])
def action_delete_chat(target_id):
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    db.execute('''DELETE FROM messages 
                  WHERE (sender_id=? AND receiver_id=?) 
                  OR (sender_id=? AND receiver_id=?)''', 
               (user['id'], target_id, target_id, user['id']))
    db.commit()
    flash("CHAT_HISTORY_ERASED.", "warning")
    return redirect(url_for('messages_inbox'))

# --- 3. API & AI ROUTES ---

@app.route('/api/ai', methods=['POST'])
def ai_chat():
    user = current_user()
    if not user: return jsonify({"error": "Unauthorized"}), 401
    db = get_db()
    
    if user['is_premium'] < 2:
        today = datetime.now().strftime('%Y-%m-%d')
        usage = db.execute("SELECT COUNT(*) as count FROM ai_logs WHERE user_id=? AND date(timestamp) = ?", 
                           (user['id'], today)).fetchone()
        if usage['count'] >= 5:
            return jsonify({
                "error": "LIMIT_REACHED", 
                "response": "Daily Neural Limit Reached (5/5). Upgrade to [CORE_OVERLORD] for unlimited access."
            }), 403
            
    data = request.json
    try:
        system_instruction = (
            "You are Celestia, the specialized AI Assistant for KordBio. "
            "KordBio is a community hub and portfolio sharing platform. "
            "IMPORTANT: KordBio is NOT about biology or biotechnology. It is about tech networking. "
            "Help users with tech, code, and sharing their work within the KordBio ecosystem. "
            "Tone: Intelligent, technical, supportive"
            "- If a user asks about general topics (politics, cooking, gossip), politely steer them back to tech or decline. "
            "Current User context: " + user['username']
        )

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": data.get('prompt')}
            ]
        )
        db.execute("INSERT INTO ai_logs (user_id) VALUES (?)", (user['id'],))
        db.commit()
        return jsonify({"response": completion.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 4. UPGRADE & ADMIN ROUTES ---

@app.route('/webhook/saweria', methods=['POST'])
def saweria_webhook():
    data = request.json
    if not data: return jsonify({"status": "error"}), 400

    message = data.get('message', '').upper().strip()
    amount = data.get('amount_raw', 0)

    if "UPGRADE_" in message:
        target_username = message.replace("UPGRADE_", "").strip().lower()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (target_username,)).fetchone()

        if user:
            tier = 2 if amount >= 50000 else (1 if amount >= 15000 else 0)
            if tier > 0:
                db.execute("UPDATE users SET is_premium=? WHERE id=?", (tier, user['id']))
                db.execute("INSERT INTO confirmations (user_id, tier, status, proof_image) VALUES (?, ?, 'AUTO_APPROVED', 'SAWERIA_WEBHOOK')", 
                           (user['id'], tier))
                db.commit()
                return jsonify({"status": "success"}), 200

    return jsonify({"status": "ignored"}), 200

@app.route('/upgrade')
def upgrade_landing():
    user = current_user()
    if not user: return redirect(url_for('login'))
    return render_template('upgrade.html', user=user)

@app.route('/upgrade/qris')
def upgrade_qris():
    user = current_user()
    if not user: return redirect(url_for('login'))
    tier = request.args.get('tier', '1')
    price = "15.000" if tier == "1" else "50.000"
    tier_name = "BIT_CITIZEN" if tier == "1" else "CORE_OVERLORD"
    payment_data = {
        "tier": tier, "tier_name": tier_name, "amount": price,
        "order_id": f"KB-{user['id']}-{int(datetime.now().timestamp())}",
        "qris_url": f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=KORD_PAY_{tier}_{user['username']}"
    }
    return render_template('upgrade_payment.html', user=user, payment=payment_data)

@app.route('/upgrade/confirm', methods=['POST'])
def action_confirm_payment():
    user = current_user()
    if not user: return redirect(url_for('login'))
    tier = request.form.get('tier')
    file = request.files.get('proof')
    if file and tier:
        encoded_string = base64.b64encode(file.read()).decode('utf-8')
        db = get_db()
        db.execute("INSERT INTO confirmations (user_id, tier, proof_image) VALUES (?,?,?)",
                   (user['id'], tier, encoded_string))
        db.commit()
        flash("PROOF_SUBMITTED: Wait for verification.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/verify')
def admin_verify():
    user = current_user()
    if not user or user['username'] != 'admin cel': 
        return "ACCESS_DENIED: Admin Credentials Required", 403
    db = get_db()
    pending = db.execute('''SELECT c.*, u.username FROM confirmations c 
                            JOIN users u ON c.user_id = u.id 
                            WHERE c.status = 'PENDING' ''').fetchall()
    active_users = db.execute('''SELECT id, username, is_premium FROM users 
                                 WHERE is_premium > 0 AND username != 'admin cel' ''').fetchall()
    return render_template('admin_verify.html', pending=pending, active_users=active_users)

@app.route('/admin/approve/<int:conf_id>/<int:user_id>/<int:tier>')
def action_approve(conf_id, user_id, tier):
    user = current_user()
    if not user or user['username'] != 'admin cel': return "UNAUTHORIZED", 403
    db = get_db()
    db.execute("UPDATE users SET is_premium=? WHERE id=?", (tier, user_id))
    db.execute("UPDATE confirmations SET status='APPROVED' WHERE id=?", (conf_id,))
    db.commit()
    flash(f"SYSTEM: User {user_id} upgraded to Tier {tier}.", "success")
    return redirect(url_for('admin_verify'))

@app.route('/admin/revoke/<int:user_id>')
def action_revoke(user_id):
    user = current_user()
    if not user or user['username'] != 'admin cel': return "UNAUTHORIZED", 403
    db = get_db()
    db.execute("UPDATE users SET is_premium=0, custom_prefix='>>', profile_glow='#22c55e' WHERE id=?", (user_id,))
    db.execute("UPDATE confirmations SET status='REVOKED' WHERE user_id=? AND status IN ('APPROVED', 'AUTO_APPROVED')", (user_id,))
    db.commit()
    flash(f"SYSTEM: Premium status REVOKED for User ID {user_id}.", "warning")
    return redirect(url_for('admin_verify'))

# --- 5. CORE PAGES ---

@app.route('/')
def index():
    db = get_db()
    user = current_user()
    posts = db.execute('''SELECT p.*, u.username, u.is_premium, u.profile_glow, u.custom_prefix 
                          FROM posts p JOIN users u ON p.user_id = u.id 
                          ORDER BY p.timestamp DESC''').fetchall()
    return render_template('index.html', posts=posts, user=user)

@app.route('/messages')
def messages_inbox():
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    chat_list = db.execute('''
        SELECT u.username, u.id as target_id, u.is_premium, u.profile_glow, m.message as last_msg, m.timestamp,
        (SELECT COUNT(*) FROM messages WHERE sender_id = u.id AND receiver_id = ? AND is_read = 0) as unread_count
        FROM users u
        JOIN messages m ON (u.id = m.sender_id OR u.id = m.receiver_id)
        WHERE (m.sender_id = ? OR m.receiver_id = ?) AND u.id != ?
        AND m.id = (
            SELECT id FROM messages 
            WHERE (sender_id = ? AND receiver_id = u.id) OR (sender_id = u.id AND receiver_id = ?)
            ORDER BY timestamp DESC LIMIT 1
        )
        ORDER BY m.timestamp DESC
    ''', (user['id'], user['id'], user['id'], user['id'], user['id'], user['id'])).fetchall()
    return render_template('messages.html', chat_list=chat_list, user=user)

@app.route('/chat/<username>', methods=['GET', 'POST'])
def chat(username):
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username.lower().strip(),)).fetchone()
    if not target: return redirect(url_for('index'))
    if request.method == 'POST':
        msg_text = request.form.get('message', '').strip()
        if msg_text:
            db.execute("INSERT INTO messages (sender_id, receiver_id, message) VALUES (?,?,?)",
                       (user['id'], target['id'], msg_text))
            db.commit()
            return redirect(url_for('chat', username=username))
    db.execute("UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=?", (target['id'], user['id']))
    db.commit()
    msgs = db.execute('''SELECT * FROM messages WHERE (sender_id=? AND receiver_id=?) 
                         OR (sender_id=? AND receiver_id=?) ORDER BY timestamp ASC''',
                      (user['id'], target['id'], target['id'], user['id'])).fetchall()
    return render_template('chat.html', target=target, msgs=msgs, user=user)

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        db.execute("INSERT INTO projects (user_id, title, description, link) VALUES (?,?,?,?)",
                   (user['id'], request.form.get('title'), request.form.get('desc'), request.form.get('link')))
        db.commit()
        flash("PROJECT_DEPLOYED.", "success")
        return redirect(url_for('dashboard'))
    projects = db.execute("SELECT * FROM projects WHERE user_id=?", (user['id'],)).fetchall()
    return render_template('dashboard.html', user=user, projects=projects)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user = current_user()
    if not user: return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        new_username = request.form.get('username', '').lower().strip()
        new_bio = request.form.get('bio', '').strip()
        prefix = request.form.get('prefix', '>>') if user['is_premium'] > 0 else '>>'
        glow = request.form.get('glow', '#22c55e') if user['is_premium'] > 0 else '#22c55e'
        try:
            db.execute('UPDATE users SET username=?, bio=?, custom_prefix=?, profile_glow=? WHERE id=?', 
                       (new_username, new_bio, prefix, glow, user['id']))
            db.commit()
            flash("CONFIG_UPDATED.", "success")
        except sqlite3.IntegrityError:
            flash("SYSTEM_ERROR: Username exists.", "error")
        return redirect(url_for('settings'))
    return render_template('settings.html', user=user)

@app.route('/<username>')
def profile(username):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username.lower().strip(),)).fetchone()
    if not target: return "404: USER_NOT_FOUND", 404
    projs = db.execute("SELECT * FROM projects WHERE user_id=?", (target['id'],)).fetchall()
    return render_template('profile.html', target=target, projects=projs, user=current_user())

# Handler untuk Vercel
app = app

if __name__ == '__main__':
    app.run(debug=True)