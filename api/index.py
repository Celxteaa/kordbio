import os, requests, base64
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq

# 1. KONFIGURASI
load_dotenv()

app = Flask(__name__, 
            template_folder='../templates', 
            static_folder='../static')

app.secret_key = os.getenv("FLASK_SECRET_KEY", "kord_pxl_core_secure_992026_final")

# --- KONFIGURASI DATABASE (FIXED FOR VERCEL/SUPABASE) ---
db_url = os.getenv("DATABASE_URL")
if db_url:
    # Memastikan skema postgresql+pg8000 digunakan agar tidak crash di Vercel
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Optimasi koneksi agar tidak kena "Cannot assign requested address"
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": 10,
    "max_overflow": 20
}

db = SQLAlchemy(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# --- MODEL DATABASE ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    bio = db.Column(db.String(255), default='Creative Developer')
    lang = db.Column(db.String(10), default='id')
    theme = db.Column(db.String(20), default='dark')
    is_premium = db.Column(db.Integer, default=0)
    custom_prefix = db.Column(db.String(10), default='>>')
    profile_glow = db.Column(db.String(10), default='#22c55e')

class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    link = db.Column(db.String(255))

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer)
    receiver_id = db.Column(db.Integer)
    message = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Integer, default=0)

class AILog(db.Model):
    __tablename__ = 'ai_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Confirmation(db.Model):
    __tablename__ = 'confirmations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    tier = db.Column(db.Integer)
    proof_image = db.Column(db.Text)
    status = db.Column(db.String(20), default='PENDING')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Inisialisasi Database (Vercel Friendly)
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"DB Error: {e}")

def current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

@app.context_processor
def inject_notifications():
    user = current_user()
    unread_count = 0
    ai_count = 0
    if user:
        unread_count = Message.query.filter_by(receiver_id=user.id, is_read=0).count()
        today = datetime.utcnow().date()
        ai_count = AILog.query.filter(AILog.user_id == user.id, db.func.date(AILog.timestamp) == today).count()
    return dict(user=user, unread_count=unread_count, ai_count=ai_count, now=datetime.now().strftime('%Y-%m-%d %H:%M'))

# --- 1. AUTH ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username'].lower().strip()).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            session['user_id'] = u.id
            flash("ACCESS_GRANTED: Welcome back.", "success")
            return redirect(url_for('dashboard'))
        flash("ACCESS_DENIED: Invalid credentials.", "error")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].lower().strip()
        reserved = ['login', 'register', 'dashboard', 'settings', 'logout', 'manage', 'api', 'chat', 'messages', 'upgrade', 'admin', 'webhook']
        if username in reserved:
            flash("SYSTEM_ERROR: Username reserved.", "error")
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash("SYSTEM_ERROR: Username already exists.", "error")
            return redirect(url_for('register'))

        new_user = User(username=username, password_hash=generate_password_hash(request.form['password']))
        db.session.add(new_user)
        db.session.commit()
        flash("USER_CREATED: Welcome to the grid.", "success")
        return redirect(url_for('login'))
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
        new_post = Post(user_id=user.id, content=content)
        db.session.add(new_post)
        db.session.commit()
        flash("LOG_ENTRY_SUCCESS.", "success")
    return redirect(url_for('index'))

@app.route('/manage/delete-post/<int:id>')
def action_delete_post(id):
    user = current_user()
    if not user: return redirect(url_for('login'))
    post = Post.query.filter_by(id=id, user_id=user.id).first()
    if post:
        db.session.delete(post)
        db.session.commit()
        flash("DATA_ERASED.", "warning")
    return redirect(url_for('index'))

@app.route('/manage/delete-project/<int:id>')
def action_delete_project(id):
    user = current_user()
    if not user: return redirect(url_for('login'))
    proj = Project.query.filter_by(id=id, user_id=user.id).first()
    if proj:
        db.session.delete(proj)
        db.session.commit()
        flash("PROJECT_WIPED.", "warning")
    return redirect(url_for('dashboard'))

@app.route('/manage/self-destruct', methods=['GET', 'POST'])
def action_self_destruct():
    user = current_user()
    if not user: return redirect(url_for('login'))
    Project.query.filter_by(user_id=user.id).delete()
    Post.query.filter_by(user_id=user.id).delete()
    Message.query.filter((Message.sender_id == user.id) | (Message.receiver_id == user.id)).delete()
    AILog.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    session.clear()
    flash("ACCOUNT_TERMINATED: All data wiped.", "error")
    return redirect(url_for('index'))

@app.route('/manage/delete-chat/<int:target_id>', methods=['GET', 'POST'])
def action_delete_chat(target_id):
    user = current_user()
    if not user: return redirect(url_for('login'))
    Message.query.filter(
        ((Message.sender_id == user.id) & (Message.receiver_id == target_id)) |
        ((Message.sender_id == target_id) & (Message.receiver_id == user.id))
    ).delete()
    db.session.commit()
    flash("CHAT_HISTORY_ERASED.", "warning")
    return redirect(url_for('messages_inbox'))

# --- 3. API & AI ROUTES ---

@app.route('/api/ai', methods=['POST'])
def ai_chat():
    user = current_user()
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    if user.is_premium < 2:
        today = datetime.utcnow().date()
        usage = AILog.query.filter(AILog.user_id == user.id, db.func.date(AILog.timestamp) == today).count()
        if usage >= 5:
            return jsonify({
                "error": "LIMIT_REACHED", 
                "response": "Daily Neural Limit Reached (5/5). Upgrade to [CORE_OVERLORD] for unlimited access."
            }), 403
            
    data = request.json
    try:
        system_instruction = (
            f"You are Celestia, AI Assistant for KordBio. User: {user.username}. "
            "KordBio is a tech networking hub. Tone: Technical, supportive."
        )

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": data.get('prompt')}
            ]
        )
        new_log = AILog(user_id=user.id)
        db.session.add(new_log)
        db.session.commit()
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
        user = User.query.filter_by(username=target_username).first()
        if user:
            tier = 2 if amount >= 50000 else (1 if amount >= 15000 else 0)
            if tier > 0:
                user.is_premium = tier
                new_conf = Confirmation(user_id=user.id, tier=tier, status='AUTO_APPROVED', proof_image='SAWERIA_WEBHOOK')
                db.session.add(new_conf)
                db.session.commit()
                return jsonify({"status": "success"}), 200
    return jsonify({"status": "ignored"}), 200

@app.route('/upgrade')
def upgrade_landing():
    user = current_user()
    if not user: return redirect(url_for('login'))
    return render_template('upgrade.html')

@app.route('/upgrade/qris')
def upgrade_qris():
    user = current_user()
    if not user: return redirect(url_for('login'))
    tier = request.args.get('tier', '1')
    price = "15.000" if tier == "1" else "50.000"
    tier_name = "BIT_CITIZEN" if tier == "1" else "CORE_OVERLORD"
    payment_data = {
        "tier": tier, "tier_name": tier_name, "amount": price,
        "order_id": f"KB-{user.id}-{int(datetime.now().timestamp())}",
        "qris_url": f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=KORD_PAY_{tier}_{user.username}"
    }
    return render_template('upgrade_payment.html', payment=payment_data)

@app.route('/upgrade/confirm', methods=['POST'])
def action_confirm_payment():
    user = current_user()
    if not user: return redirect(url_for('login'))
    tier = request.form.get('tier')
    file = request.files.get('proof')
    if file and tier:
        encoded_string = base64.b64encode(file.read()).decode('utf-8')
        new_conf = Confirmation(user_id=user.id, tier=tier, proof_image=encoded_string)
        db.session.add(new_conf)
        db.session.commit()
        flash("PROOF_SUBMITTED: Wait for verification.", "success")
    return redirect(url_for('dashboard'))

@app.route('/admin/verify')
def admin_verify():
    user = current_user()
    if not user or user.username != 'admin cel': return "ACCESS_DENIED", 403
    
    pending = db.session.query(
        Confirmation.id, 
        Confirmation.user_id, 
        Confirmation.tier, 
        Confirmation.proof_image, 
        User.username
    ).join(User, Confirmation.user_id == User.id)\
     .filter(Confirmation.status == 'PENDING').all()
    
    active_users = User.query.filter(User.is_premium > 0, User.username != 'admin cel').all()
    return render_template('admin_verify.html', pending=pending, active_users=active_users, user=user)

@app.route('/admin/approve/<int:conf_id>/<int:user_id>/<int:tier>')
def action_approve(conf_id, user_id, tier):
    user = current_user()
    if not user or user.username != 'admin cel': return "UNAUTHORIZED", 403
    u = User.query.get(user_id)
    c = Confirmation.query.get(conf_id)
    if u and c:
        u.is_premium = tier
        c.status = 'APPROVED'
        db.session.commit()
        flash(f"SYSTEM: User {u.username} upgraded.", "success")
    return redirect(url_for('admin_verify'))

@app.route('/admin/revoke/<int:user_id>')
def action_revoke(user_id):
    user = current_user()
    if not user or user.username != 'admin cel': return "UNAUTHORIZED", 403
    u = User.query.get(user_id)
    if u:
        u.is_premium = 0
        Confirmation.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        flash(f"SYSTEM: Node {u.username} access revoked.", "warning")
    return redirect(url_for('admin_verify'))

# --- 5. CORE PAGES ---

@app.route('/')
def index():
    user = current_user()
    posts_data = db.session.query(
        Post.id, Post.content, Post.timestamp, Post.user_id,
        User.username, User.is_premium
    ).join(User, Post.user_id == User.id).order_by(Post.timestamp.desc()).all()
    
    return render_template('index.html', posts=posts_data, user=user)

@app.route('/messages')
def messages_inbox():
    user = current_user()
    if not user: return redirect(url_for('login'))
    
    chat_list_raw = db.session.execute(db.text('''
        SELECT 
            u.username, 
            u.id as target_id, 
            u.is_premium, 
            u.profile_glow, 
            m.message as last_msg, 
            m.timestamp,
            (SELECT COUNT(*) FROM messages WHERE sender_id = u.id AND receiver_id = :uid AND is_read = 0) as unread_count
        FROM users u
        JOIN messages m ON (u.id = m.sender_id OR u.id = m.receiver_id)
        WHERE (m.sender_id = :uid OR m.receiver_id = :uid) AND u.id != :uid
        AND m.id = (
            SELECT id FROM messages 
            WHERE (sender_id = :uid AND receiver_id = u.id) OR (sender_id = u.id AND receiver_id = :uid)
            ORDER BY timestamp DESC LIMIT 1
        )
        ORDER BY m.timestamp DESC
    '''), {'uid': user.id}).fetchall()
    
    formatted_chats = []
    for row in chat_list_raw:
        formatted_chats.append({
            'username': row.username,
            'target_id': row.target_id,
            'is_premium': row.is_premium,
            'profile_glow': row.profile_glow,
            'last_msg': row.last_msg,
            'timestamp': str(row.timestamp),
            'unread_count': row.unread_count
        })
        
    return render_template('messages.html', chat_list=formatted_chats, user=user)

@app.route('/chat/<username>', methods=['GET', 'POST'])
def chat(username):
    user = current_user()
    if not user: return redirect(url_for('login'))
    target = User.query.filter_by(username=username.lower().strip()).first()
    if not target: return redirect(url_for('index'))
    if request.method == 'POST':
        msg_text = request.form.get('message', '').strip()
        if msg_text:
            new_msg = Message(sender_id=user.id, receiver_id=target.id, message=msg_text)
            db.session.add(new_msg)
            db.session.commit()
            return redirect(url_for('chat', username=username))
    Message.query.filter_by(sender_id=target.id, receiver_id=user.id).update({Message.is_read: 1})
    db.session.commit()
    msgs = Message.query.filter(
        ((Message.sender_id == user.id) & (Message.receiver_id == target.id)) |
        ((Message.sender_id == target.id) & (Message.receiver_id == user.id))
    ).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', target=target, msgs=msgs)

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    user = current_user()
    if not user: return redirect(url_for('login'))
    if request.method == 'POST':
        new_p = Project(user_id=user.id, title=request.form.get('title'), 
                        description=request.form.get('desc'), link=request.form.get('link'))
        db.session.add(new_p)
        db.session.commit()
        flash("PROJECT_DEPLOYED.", "success")
        return redirect(url_for('dashboard'))
    projects = Project.query.filter_by(user_id=user.id).all()
    return render_template('dashboard.html', projects=projects, user=user)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user = current_user()
    if not user: return redirect(url_for('login'))
    if request.method == 'POST':
        user.username = request.form.get('username', '').lower().strip()
        user.bio = request.form.get('bio', '').strip()
        if user.is_premium > 0:
            user.custom_prefix = request.form.get('prefix', '>>')
            user.profile_glow = request.form.get('glow', '#22c55e')
        try:
            db.session.commit()
            flash("CONFIG_UPDATED.", "success")
        except:
            db.session.rollback()
            flash("SYSTEM_ERROR: Username exists.", "error")
        return redirect(url_for('settings'))
    return render_template('settings.html')

@app.route('/<username>')
def profile(username):
    target = User.query.filter_by(username=username.lower().strip()).first()
    if not target: return "404: USER_NOT_FOUND", 404
    projs = Project.query.filter_by(user_id=target.id).all()
    return render_template('profile.html', target=target, projects=projs)

# Ekspor app untuk Vercel
app = app

if __name__ == '__main__':
    app.run(debug=True)