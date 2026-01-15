import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import sqlite3
from datetime import datetime

# লগিং সেটআপ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== ডাটাবেস ক্লাস ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('movies.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        # Users টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'user',
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Movies টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                year TEXT,
                quality TEXT,
                language TEXT,
                size TEXT,
                download_link TEXT,
                uploader_id INTEGER,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Agents টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS agents (
                agent_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Requests টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                movie_name TEXT,
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        # অ্যাডমিন অ্যাড (আপনার আইডি)
        self.cursor.execute('INSERT OR IGNORE INTO users (user_id, role) VALUES (?, ?)', (5347353883, 'admin'))
        self.conn.commit()
    
    def get_user_role(self, user_id):
        self.cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        
        # নতুন ইউজার
        self.cursor.execute('INSERT INTO users (user_id, role) VALUES (?, ?)', (user_id, 'user'))
        self.conn.commit()
        return 'user'
    
    def add_movie(self, data):
        self.cursor.execute('''
            INSERT INTO movies (title, year, quality, language, size, download_link, uploader_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (data['title'], data['year'], data['quality'], data['language'], 
              data['size'], data['download_link'], data['uploader_id']))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_movies(self, limit=10):
        self.cursor.execute('SELECT * FROM movies ORDER BY id DESC LIMIT ?', (limit,))
        return self.cursor.fetchall()
    
    def search_movies(self, query):
        self.cursor.execute('SELECT * FROM movies WHERE title LIKE ? ORDER BY id DESC', (f'%{query}%',))
        return self.cursor.fetchall()
    
    def get_movie_by_id(self, movie_id):
        self.cursor.execute('SELECT * FROM movies WHERE id = ?', (movie_id,))
        return self.cursor.fetchone()
    
    def get_agents(self):
        self.cursor.execute('SELECT agent_id FROM agents')
        return [row[0] for row in self.cursor.fetchall()]
    
    def add_agent(self, agent_id, admin_id):
        # ইউজার টেবিলে অ্যাড করুন
        self.cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (agent_id,))
        self.cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', ('agent', agent_id))
        # এজেন্ট টেবিলে
        self.cursor.execute('INSERT OR REPLACE INTO agents (agent_id, added_by) VALUES (?, ?)', (agent_id, admin_id))
        self.conn.commit()
        return True
    
    def remove_agent(self, agent_id):
        self.cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', ('user', agent_id))
        self.cursor.execute('DELETE FROM agents WHERE agent_id = ?', (agent_id,))
        self.conn.commit()
        return True
    
    def get_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM users')
        users = self.cursor.fetchone()[0]
        
        self.cursor.execute('SELECT COUNT(*) FROM movies')
        movies = self.cursor.fetchone()[0]
        
        self.cursor.execute('SELECT COUNT(*) FROM agents')
        agents = self.cursor.fetchone()[0]
        
        self.cursor.execute('SELECT COUNT(*) FROM requests WHERE status = "pending"')
        pending_requests = self.cursor.fetchone()[0]
        
        return {
            'users': users, 
            'movies': movies, 
            'agents': agents,
            'pending_requests': pending_requests
        }
    
    def add_request(self, user_id, movie_name):
        self.cursor.execute('INSERT INTO requests (user_id, movie_name) VALUES (?, ?)', (user_id, movie_name))
        self.conn.commit()
        return True
    
    def get_user_requests(self, user_id):
        self.cursor.execute('SELECT * FROM requests WHERE user_id = ? ORDER BY request_date DESC', (user_id,))
        return self.cursor.fetchall()
    
    def delete_movie(self, movie_id):
        self.cursor.execute('DELETE FROM movies WHERE id = ?', (movie_id,))
        self.conn.commit()
        return True

db = Database()

# ==================== বট ফাংশন ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_user_role(user_id)
    
    welcome_text = """
    🎬 *Welcome to Movie Share Bot!* 🍿

    এই বটের মাধ্যমে আপনি:
    • নতুন মুভি ডাউনলোড করতে পারবেন
    • মুভি সার্চ করতে পারবেন
    • মুভি রিকোয়েস্ট করতে পারবেন

    নিচের বাটনগুলো ব্যবহার করুন:"""
    
    keyboard = [
        [InlineKeyboardButton("🔍 মুভি সার্চ", callback_data="search")],
        [InlineKeyboardButton("📥 নতুন মুভি", callback_data="latest")],
        [InlineKeyboardButton("📝 মুভি রিকোয়েস্ট", callback_data="request_movie")]
    ]
    
    # অ্যাডমিন/এজেন্ট মেনু
    if role in ['admin', 'agent']:
        keyboard.append([InlineKeyboardButton("📤 মুভি আপলোড", callback_data="upload_movie")])
    
    # শুধু অ্যাডমিন
    if role == 'admin':
        keyboard.append([InlineKeyboardButton("👥 এজেন্ট ম্যানেজ", callback_data="manage_agents")])
        keyboard.append([InlineKeyboardButton("📊 স্ট্যাটস", callback_data="stats")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    role = db.get_user_role(user_id)
    data = query.data
    
    # ডিবাগিং
    print(f"Button clicked: {data} by user {user_id}")
    
    # হোম পেজ
    if data == "home":
        await start_callback(query, user_id)
    
    # মুভি ব্রাউজ
    elif data == "latest":
        await show_latest(query)
    
    # সার্চ
    elif data == "search":
        await search_movie_prompt(query)
    
    # রিকোয়েস্ট
    elif data == "request_movie":
        await request_movie_prompt(query)
    
    # মুভি আপলোড - এজেন্ট/অ্যাডমিন
    elif data == "upload_movie" and role in ['admin', 'agent']:
        context.user_data.clear()
        context.user_data['upload_mode'] = True
        context.user_data['upload_step'] = 'title'
        context.user_data['movie_data'] = {}
        await upload_step_title(query)
    
    # এজেন্ট ম্যানেজমেন্ট - শুধু অ্যাডমিন
    elif data == "manage_agents" and role == 'admin':
        await manage_agents_menu(query)
    
    # স্ট্যাটস - শুধু অ্যাডমিন
    elif data == "stats" and role == 'admin':
        await show_stats(query)
    
    # আপলোড কনফার্ম
    elif data == "confirm_upload":
        await confirm_upload(query, context)
    
    # আপলোড ক্যান্সেল
    elif data == "cancel_upload":
        context.user_data.clear()
        await query.edit_message_text("❌ আপলোড বাতিল হয়েছে!", parse_mode='Markdown')
        await start_callback(query, user_id)
    
    # মুভি ডিটেলস দেখান
    elif data.startswith("movie_"):
        movie_id = int(data.split("_")[1])
        await show_movie_details(query, movie_id)
    
    # এজেন্ট ডিলিট
    elif data.startswith("delete_agent_"):
        agent_id = int(data.split("_")[2])
        db.remove_agent(agent_id)
        await query.edit_message_text(f"✅ এজেন্ট {agent_id} রিমুভ করা হয়েছে!", parse_mode='Markdown')
        await manage_agents_menu(query)
    
    # এজেন্ট অ্যাড প্রম্পট
    elif data == "add_agent_prompt":
        await add_agent_prompt(query)
    
    # রিকোয়েস্ট লিস্ট
    elif data == "my_requests":
        await show_my_requests(query, user_id)
    
    # মুভি ডিলিট (অ্যাডমিন)
    elif data.startswith("delete_movie_") and role == 'admin':
        movie_id = int(data.split("_")[2])
        db.delete_movie(movie_id)
        await query.edit_message_text(f"✅ মুভি {movie_id} ডিলিট করা হয়েছে!", parse_mode='Markdown')
        await show_latest(query)
    
    # ডিফল্ট
    else:
        await query.edit_message_text("⚠️ এই ফিচারটি এখনো এভেইলেবল নয়!", parse_mode='Markdown')

async def start_callback(query, user_id):
    role = db.get_user_role(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🔍 মুভি সার্চ", callback_data="search")],
        [InlineKeyboardButton("📥 নতুন মুভি", callback_data="latest")],
        [InlineKeyboardButton("📝 মুভি রিকোয়েস্ট", callback_data="request_movie")]
    ]
    
    if role in ['admin', 'agent']:
        keyboard.append([InlineKeyboardButton("📤 মুভি আপলোড", callback_data="upload_movie")])
    
    if role == 'admin':
        keyboard.append([
            InlineKeyboardButton("👥 এজেন্ট ম্যানেজ", callback_data="manage_agents"),
            InlineKeyboardButton("📊 স্ট্যাটস", callback_data="stats")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🏠 *মেইন মেনু* - নিচের বাটনগুলো ব্যবহার করুন:", 
                                  reply_markup=reply_markup, parse_mode='Markdown')

# ==================== মুভি সার্চ ও ব্রাউজ ====================
async def search_movie_prompt(query):
    await query.edit_message_text(
        "🔍 *মুভি সার্চ*\n\nযে মুভি খুঁজছেন তার নাম লিখে পাঠান:\n\nউদাহরণ: `Avatar`, `KGF`, `Pathaan`",
        parse_mode='Markdown'
    )

async def show_latest(query):
    movies = db.get_movies(10)
    
    if not movies:
        await query.edit_message_text("📭 এখনো কোন মুভি আপলোড করা হয়নি!", parse_mode='Markdown')
        return
    
    text = "📥 *নতুন মুভি লিস্ট:*\n\n"
    keyboard = []
    
    for movie in movies:
        movie_id, title, year, quality, language, size, link, uploader, date = movie
        display_title = title[:30] + "..." if len(title) > 30 else title
        text += f"🎬 *{display_title}* ({year})\n"
        text += f"   ⚡ {quality} | 🗣️ {language} | 💾 {size}\n\n"
        keyboard.append([InlineKeyboardButton(
            f"🎬 {display_title}", 
            callback_data=f"movie_{movie_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 হোম", callback_data="home")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_movie_details(query, movie_id):
    movie = db.get_movie_by_id(movie_id)
    
    if not movie:
        await query.edit_message_text("❌ মুভি পাওয়া যায়নি!", parse_mode='Markdown')
        return
    
    movie_id, title, year, quality, language, size, link, uploader, date = movie
    
    text = f"""
🎬 *{title}* ({year})

📊 *ডিটেলস:*
⚡ কোয়ালিটি: {quality}
🗣️ ভাষা: {language}
💾 সাইজ: {size}
📅 আপলোড: {date[:10] if date else 'N/A'}

🔗 *ডাউনলোড লিংক:*
`{link}`
"""
    
    keyboard = [
        [InlineKeyboardButton("⬇️ ডাউনলোড লিংক", url=link)],
        [InlineKeyboardButton("🔙 পিছনে", callback_data="latest")]
    ]
    
    # অ্যাডমিন হলে ডিলিট বাটন
    user_id = query.from_user.id
    role = db.get_user_role(user_id)
    if role == 'admin':
        keyboard.append([InlineKeyboardButton("🗑️ মুভি ডিলিট", callback_data=f"delete_movie_{movie_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== মুভি আপলোড সিস্টেম ====================
async def upload_step_title(query):
    text = """
📤 *মুভি আপলোড সিস্টেম*

🎬 *ধাপ ১/৬: মুভির নাম*
মুভির পূর্ণ নাম লিখুন:

উদাহরণ:
• Avatar: The Way of Water
• KGF Chapter 2
• Pathaan
"""
    
    keyboard = [[InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def upload_step_year(query, title):
    text = f"""
✅ নাম সেভ হয়েছে: *{title}*

📅 *ধাপ ২/৬: মুভির সাল*
মুভি প্রকাশের সাল লিখুন:

উদাহরণ:
• 2023
• 2022
• 2021
"""
    
    keyboard = [[InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def upload_step_quality(query, title, year):
    text = f"""
✅ সাল সেভ হয়েছে: *{year}*

⚡ *ধাপ ৩/৬: ভিডিও কোয়ালিটি*
ভিডিওর রেজোলিউশন লিখুন:

উদাহরণ:
• 1080p WEB-DL
• 720p HDRip
• 480p
• 4K UHD
"""
    
    keyboard = [[InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def upload_step_language(query, title, year, quality):
    text = f"""
✅ কোয়ালিটি সেভ হয়েছে: *{quality}*

🗣️ *ধাপ ৪/৬: অডিও/সাবটাইটেল*
ভাষা লিখুন:

উদাহরণ:
• বাংলা ডাবিং
• বাংলা সাবটাইটেল
• হিন্দি ডাবিং
• ইংরেজি
"""
    
    keyboard = [[InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def upload_step_size(query, title, year, quality, language):
    text = f"""
✅ ভাষা সেভ হয়েছে: *{language}*

💾 *ধাপ ৫/৬: ফাইল সাইজ*
মুভির ফাইল সাইজ লিখুন:

উদাহরণ:
• 1.5GB
• 2.3GB
• 850MB
• 4.7GB
"""
    
    keyboard = [[InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def upload_step_link(query, title, year, quality, language, size):
    text = f"""
✅ সাইজ সেভ হয়েছে: *{size}*

🔗 *ধাপ ৬/৬: ডাউনলোড লিংক*
ডাউনলোড লিংক দিন:

উদাহরণ:
• https://drive.google.com/file/...
• https://mega.nz/file/...
• https://example.com/download.zip

⚠️ *সতর্কতা:* ভ্যালিড লিংক দিন!
"""
    
    keyboard = [[InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def upload_show_summary(query, context):
    movie_data = context.user_data.get('movie_data', {})
    
    if not movie_data:
        await query.edit_message_text("❌ তথ্য পাওয়া যায়নি!", parse_mode='Markdown')
        return
    
    text = f"""
📋 *আপলোড সামারি*

🎬 *নাম:* {movie_data.get('title', 'N/A')}
📅 *সাল:* {movie_data.get('year', 'N/A')}
⚡ *কোয়ালিটি:* {movie_data.get('quality', 'N/A')}
🗣️ *ভাষা:* {movie_data.get('language', 'N/A')}
💾 *সাইজ:* {movie_data.get('size', 'N/A')}
🔗 *লিংক:* {movie_data.get('link', 'N/A')[:50]}...

✅ সবকিছু ঠিক আছে?
"""
    
    keyboard = [
        [InlineKeyboardButton("✅ আপলোড করুণ", callback_data="confirm_upload")],
        [InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def confirm_upload(query, context):
    user_id = query.from_user.id
    movie_data = context.user_data.get('movie_data', {})
    
    if not movie_data:
        await query.edit_message_text("❌ তথ্য পাওয়া যায়নি!", parse_mode='Markdown')
        return
    
    try:
        # ডাটাবেসে সেভ করুন
        movie_id = db.add_movie({
            'title': movie_data.get('title', ''),
            'year': movie_data.get('year', ''),
            'quality': movie_data.get('quality', ''),
            'language': movie_data.get('language', ''),
            'size': movie_data.get('size', ''),
            'download_link': movie_data.get('link', ''),
            'uploader_id': user_id
        })
        
        # ক্লিয়ার ডাটা
        context.user_data.clear()
        
        success_text = f"""
✅ *মুভি সফলভাবে আপলোড হয়েছে!*

🎬 *নাম:* {movie_data.get('title', '')}
📅 *সাল:* {movie_data.get('year', '')}
⚡ *কোয়ালিটি:* {movie_data.get('quality', '')}
🗣️ *ভাষা:* {movie_data.get('language', '')}
💾 *সাইজ:* {movie_data.get('size', '')}

📌 মুভি আইডি: `{movie_id}`
🕐 সময়: {datetime.now().strftime('%H:%M:%S')}

ইউজাররা এখন ডাউনলোড করতে পারবে।
"""
        
        keyboard = [[InlineKeyboardButton("🏠 হোম", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    except Exception as e:
        await query.edit_message_text(f"❌ আপলোড ব্যর্থ: {str(e)}", parse_mode='Markdown')

# ==================== এজেন্ট ম্যানেজমেন্ট ====================
async def manage_agents_menu(query):
    agents = db.get_agents()
    
    text = "👥 *এজেন্ট ম্যানেজমেন্ট*\n\n"
    
    if agents:
        text += "📋 *সক্রিয় এজেন্ট লিস্ট:*\n"
        for agent_id in agents:
            text += f"• `{agent_id}`\n"
        text += f"\nমোট এজেন্ট: {len(agents)}"
    else:
        text += "📭 *কোন এজেন্ট নেই*"
    
    keyboard = [
        [InlineKeyboardButton("➕ এজেন্ট অ্যাড", callback_data="add_agent_prompt")],
    ]
    
    if agents:
        for agent_id in agents[:5]:  # সর্বোচ্চ ৫টি
            keyboard.append([InlineKeyboardButton(
                f"❌ এজেন্ট {agent_id} রিমুভ", 
                callback_data=f"delete_agent_{agent_id}"
            )])
    
    keyboard.append([InlineKeyboardButton("🔙 হোম", callback_data="home")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_agent_prompt(query):
    await query.edit_message_text(
        "➕ *নতুন এজেন্ট অ্যাড*\n\n"
        "নতুন এজেন্টের **টেলিগ্রাম আইডি** পাঠান:\n\n"
        "📌 *উদাহরণ:* `1234567890`\n\n"
        "ℹ️ *নোট:* ব্যক্তিকে আগে বটে /start করতে হবে",
        parse_mode='Markdown'
    )

# ==================== রিকোয়েস্ট সিস্টেম ====================
async def request_movie_prompt(query):
    await query.edit_message_text(
        "📝 *মুভি রিকোয়েস্ট*\n\n"
        "আপনি কোন মুভি চান? নাম লিখে পাঠান:\n\n"
        "📌 *উদাহরণ:*\n"
        "• Avatar 3\n"
        "• Salaar Part 2\n"
        "• Animal 2\n\n"
        "✅ আপনার রিকোয়েস্ট সেভ হবে এবং এজেন্টরা দেখতে পাবে।",
        parse_mode='Markdown'
    )

async def show_my_requests(query, user_id):
    requests = db.get_user_requests(user_id)
    
    if not requests:
        await query.edit_message_text("📭 আপনি এখনো কোন মুভি রিকোয়েস্ট করেননি!", parse_mode='Markdown')
        return
    
    text = "📋 *আপনার রিকোয়েস্ট লিস্ট:*\n\n"
    
    for req in requests[:10]:  # সর্বোচ্চ ১০টি
        req_id, user_id, movie_name, date, status = req
        status_icon = "⏳" if status == "pending" else "✅" if status == "completed" else "❌"
        text += f"{status_icon} *{movie_name}*\n"
        text += f"   📅 {date[:10]} | Status: {status}\n\n"
    
    text += f"\nমোট রিকোয়েস্ট: {len(requests)}"
    
    keyboard = [[InlineKeyboardButton("🔙 হোম", callback_data="home")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== স্ট্যাটিস্টিকস ====================
async def show_stats(query):
    stats = db.get_stats()
    
    text = f"""
📊 *বট স্ট্যাটিস্টিকস*

👥 *ইউজার:* {stats['users']}
🎬 *মুভি:* {stats['movies']}
👷 *এজেন্ট:* {stats['agents']}
📝 *পেন্ডিং রিকোয়েস্ট:* {stats['pending_requests']}

🔄 *লাস্ট আপডেট:* {datetime.now().strftime('%H:%M:%S')}

⚡ Powered by Movie Share Bot
"""
    
    keyboard = [[InlineKeyboardButton("🔙 হোম", callback_data="home")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== মেসেজ হ্যান্ডলার ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    role = db.get_user_role(user_id)
    
    print(f"Message received from {user_id}: {message_text[:50]}...")
    
    # ১. যদি আপলোড মোডে থাকে
    if context.user_data.get('upload_mode'):
        await handle_upload_message(update, context)
        return
    
    # ২. যদি অ্যাডমিন এজেন্ট আইডি পাঠায়
    if role == 'admin' and message_text.isdigit():
        agent_id = int(message_text)
        success = db.add_agent(agent_id, user_id)
        if success:
            await update.message.reply_text(f"✅ এজেন্ট `{agent_id}` সফলভাবে অ্যাড করা হয়েছে!", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ এজেন্ট অ্যাড করতে সমস্যা!", parse_mode='Markdown')
        return
    
    # ৩. যদি মুভি সার্চ/রিকোয়েস্ট হয়
    if len(message_text) > 1:
        # প্রথমে সার্চ করুন
        movies = db.search_movies(message_text)
        
        if movies:
            # মুভি পাওয়া গেছে
            text = f"🔍 *'{message_text}' এর রেজাল্ট:*\n\n"
            keyboard = []
            
            for movie in movies[:5]:
                movie_id, title, year, quality, language, size, link, uploader, date = movie
                display_title = title[:25] + "..." if len(title) > 25 else title
                text += f"🎬 *{display_title}* ({year})\n"
                text += f"   ⚡ {quality} | 🗣️ {language}\n\n"
                keyboard.append([InlineKeyboardButton(
                    f"🎬 {display_title}", 
                    callback_data=f"movie_{movie_id}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 হোম", callback_data="home")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        
        else:
            # মুভি পাওয়া যায়নি, রিকোয়েস্ট হিসেবে সেভ করুন
            success = db.add_request(user_id, message_text)
            if success:
                await update.message.reply_text(
                    f"🔍 *'{message_text}' নামে কোন মুভি পাওয়া যায়নি!*\n\n"
                    "✅ আপনার রিকোয়েস্ট সেভ করা হয়েছে।\n"
                    "এজেন্টরা এটি দেখতে পাবে এবং শীঘ্রই আপলোড করবে।",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("❌ রিকোয়েস্ট সেভ করতে সমস্যা!", parse_mode='Markdown')
        
        return
    
    # ৪. ডিফল্ট রেসপন্স
    await update.message.reply_text("✉️ মেসেজ রিসিভ হয়েছে!", parse_mode='Markdown')

async def handle_upload_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    step = context.user_data.get('upload_step', 'title')
    movie_data = context.user_data.get('movie_data', {})
    
    print(f"Upload step {step}: {message_text}")
    
    if step == 'title':
        movie_data['title'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'year'
        await upload_step_year_callback(update, message_text)
    
    elif step == 'year':
        movie_data['year'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'quality'
        await upload_step_quality_callback(update, movie_data['title'], message_text)
    
    elif step == 'quality':
        movie_data['quality'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'language'
        await upload_step_language_callback(update, movie_data['title'], movie_data['year'], message_text)
    
    elif step == 'language':
        movie_data['language'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'size'
        await upload_step_size_callback(update, movie_data['title'], movie_data['year'], 
                                       movie_data['quality'], message_text)
    
    elif step == 'size':
        movie_data['size'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'link'
        await upload_step_link_callback(update, movie_data['title'], movie_data['year'],
                                       movie_data['quality'], movie_data['language'], message_text)
    
    elif step == 'link':
        movie_data['link'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'summary'
        await upload_show_summary_callback(update, context)

async def upload_step_year_callback(update, title):
    await update.message.reply_text(
        f"✅ নাম সেভ হয়েছে: *{title}*\n\n"
        "📅 *এখন মুভির সাল লিখুন:*\n"
        "উদাহরণ: 2023, 2022, 2021",
        parse_mode='Markdown'
    )

async def upload_step_quality_callback(update, title, year):
    await update.message.reply_text(
        f"✅ সাল সেভ হয়েছে: *{year}*\n\n"
        "⚡ *এখন ভিডিও কোয়ালিটি লিখুন:*\n"
        "উদাহরণ: 1080p WEB-DL, 720p HDRip",
        parse_mode='Markdown'
    )

async def upload_step_language_callback(update, title, year, quality):
    await update.message.reply_text(
        f"✅ কোয়ালিটি সেভ হয়েছে: *{quality}*\n\n"
        "🗣️ *এখন ভাষা লিখুন:*\n"
        "উদাহরণ: বাংলা ডাবিং, বাংলা সাবটাইটেল",
        parse_mode='Markdown'
    )

async def upload_step_size_callback(update, title, year, quality, language):
    await update.message.reply_text(
        f"✅ ভাষা সেভ হয়েছে: *{language}*\n\n"
        "💾 *এখন ফাইল সাইজ লিখুন:*\n"
        "উদাহরণ: 1.5GB, 2.3GB, 850MB",
        parse_mode='Markdown'
    )

async def upload_step_link_callback(update, title, year, quality, language, size):
    await update.message.reply_text(
        f"✅ সাইজ সেভ হয়েছে: *{size}*\n\n"
        "🔗 *এখন ডাউনলোড লিংক দিন:*\n"
        "উদাহরণ: https://drive.google.com/...\n\n"
        "⚠️ ভ্যালিড লিংক দিন!",
        parse_mode='Markdown'
    )

async def upload_show_summary_callback(update, context):
    movie_data = context.user_data.get('movie_data', {})
    
    summary = f"""
📋 *আপলোড সামারি*

🎬 *নাম:* {movie_data.get('title', 'N/A')}
📅 *সাল:* {movie_data.get('year', 'N/A')}
⚡ *কোয়ালিটি:* {movie_data.get('quality', 'N/A')}
🗣️ *ভাষা:* {movie_data.get('language', 'N/A')}
💾 *সাইজ:* {movie_data.get('size', 'N/A')}
🔗 *লিংক:* {movie_data.get('link', 'N/A')[:100]}...

*আপলোড কনফার্ম করতে নিচের বাটনে ক্লিক করুন:*
"""
    
    keyboard = [
        [InlineKeyboardButton("✅ আপলোড কনফার্ম", callback_data="confirm_upload")],
        [InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(summary, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== অ্যাডমিন কমান্ড ====================
async def admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_user_role(user_id)
    
    if role != 'admin':
        await update.message.reply_text("❌ আপনার অ্যাডমিন এক্সেস নেই!", parse_mode='Markdown')
        return
    
    text = """
🛠️ *অ্যাডমিন কমান্ডস*

/addagent <id> - নতুন এজেন্ট অ্যাড
/removeagent <id> - এজেন্ট রিমুভ
/stats - স্ট্যাটিস্টিকস
/delete <movie_id> - মুভি ডিলিট
/agents - এজেন্ট লিস্ট
"""
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def add_agent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_user_role(user_id)
    
    if role != 'admin':
        await update.message.reply_text("❌ আপনার অ্যাডমিন এক্সেস নেই!", parse_mode='Markdown')
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /addagent <telegram_id>", parse_mode='Markdown')
        return
    
    try:
        agent_id = int(context.args[0])
        success = db.add_agent(agent_id, user_id)
        
        if success:
            await update.message.reply_text(f"✅ এজেন্ট `{agent_id}` সফলভাবে অ্যাড করা হয়েছে!", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ এজেন্ট অ্যাড করতে সমস্যা!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ ভ্যালিড আইডি দিন!", parse_mode='Markdown')

async def remove_agent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_user_role(user_id)
    
    if role != 'admin':
        await update.message.reply_text("❌ আপনার অ্যাডমিন এক্সেস নেই!", parse_mode='Markdown')
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /removeagent <telegram_id>", parse_mode='Markdown')
        return
    
    try:
        agent_id = int(context.args[0])
        success = db.remove_agent(agent_id)
        
        if success:
            await update.message.reply_text(f"✅ এজেন্ট `{agent_id}` রিমুভ করা হয়েছে!", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ এজেন্ট রিমুভ করতে সমস্যা!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ ভ্যালিড আইডি দিন!", parse_mode='Markdown')

# ==================== মেইন ফাংশন ====================
def main():
    # বট টোকেন
    BOT_TOKEN = "5649845146:AAGuL82r0Ib-vN2YkRl2HzqFBZjQtWcjTps"
    
    # অ্যাপ্লিকেশন তৈরি
    application = Application.builder().token(BOT_TOKEN).build()
    
    # কমান্ড হ্যান্ডলার
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_commands))
    application.add_handler(CommandHandler("addagent", add_agent_command))
    application.add_handler(CommandHandler("removeagent", remove_agent_command))
    application.add_handler(CommandHandler("stats", show_stats_command))
    
    # বাটন হ্যান্ডলার
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # মেসেজ হ্যান্ডলার
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # বট শুরু
    print("=" * 50)
    print("🎬 Movie Bot চালু হয়েছে!")
    print(f"🔑 Admin ID: 5347353883")
    print(f"🤖 Bot Token: {BOT_TOKEN[:15]}...")
    print("📱 Telegram এ যান এবং বটে /start দিন")
    print("=" * 50)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_user_role(user_id)
    
    if role != 'admin':
        await update.message.reply_text("❌ আপনার অ্যাডমিন এক্সেস নেই!", parse_mode='Markdown')
        return
    
    stats = db.get_stats()
    
    text = f"""
📊 *ডিটেইলড স্ট্যাটিস্টিকস*

👥 *মোট ইউজার:* {stats['users']}
🎬 *মোট মুভি:* {stats['movies']}
👷 *এজেন্ট সংখ্যা:* {stats['agents']}
📝 *পেন্ডিং রিকোয়েস্ট:* {stats['pending_requests']}

🕐 *সিস্টেম টাইম:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    await update.message.reply_text(text, parse_mode='Markdown')

if __name__ == '__main__':
    main()
