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
                thumbnail TEXT,
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
            INSERT INTO movies (title, year, quality, language, size, download_link, thumbnail, uploader_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['title'], data['year'], data['quality'], data['language'], 
              data['size'], data['download_link'], data.get('thumbnail', ''), data['uploader_id']))
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
    
    def get_agents_with_details(self):
        self.cursor.execute('''
            SELECT a.agent_id, u.username, a.added_date 
            FROM agents a 
            LEFT JOIN users u ON a.agent_id = u.user_id
        ''')
        return self.cursor.fetchall()
    
    def add_agent(self, agent_id, admin_id):
        # ইউজার টেবিলে চেক করুন
        self.cursor.execute('SELECT role FROM users WHERE user_id = ?', (agent_id,))
        result = self.cursor.fetchone()
        
        if result:
            # ইউজার আছে, রোল আপডেট করুন
            self.cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', ('agent', agent_id))
        else:
            # নতুন ইউজার অ্যাড করুন
            self.cursor.execute('INSERT INTO users (user_id, role) VALUES (?, ?)', (agent_id, 'agent'))
        
        # এজেন্ট টেবিলে অ্যাড করুন
        self.cursor.execute('INSERT OR REPLACE INTO agents (agent_id, added_by) VALUES (?, ?)', (agent_id, admin_id))
        self.conn.commit()
        return True
    
    def remove_agent(self, agent_id):
        # ইউজার টেবিলে রোল আপডেট
        self.cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', ('user', agent_id))
        # এজেন্ট টেবিল থেকে রিমুভ
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
        [InlineKeyboardButton("🔍 মুভি সার্চ", callback_data="browse_search")],
        [InlineKeyboardButton("📥 নতুন মুভি", callback_data="browse_latest")],
        [InlineKeyboardButton("📝 মুভি রিকোয়েস্ট", callback_data="browse_request")]
    ]
    
    # অ্যাডমিন/এজেন্ট মেনু
    if role in ['admin', 'agent']:
        keyboard.append([InlineKeyboardButton("📤 মুভি আপলোড", callback_data="browse_upload")])
    
    # শুধু অ্যাডমিন
    if role == 'admin':
        keyboard.append([
            InlineKeyboardButton("👥 এজেন্ট ম্যানেজ", callback_data="browse_agents"),
            InlineKeyboardButton("📊 স্ট্যাটস", callback_data="browse_stats")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    role = db.get_user_role(user_id)
    data = query.data
    
    print(f"Button: {data}, User: {user_id}, Role: {role}")
    
    # হোম পেজ
    if data == "home":
        await start_callback(query, user_id)
    
    # ব্রাউজ মেনু
    elif data == "browse_search":
        await search_movie_prompt(query)
    
    elif data == "browse_latest":
        await show_latest(query)
    
    elif data == "browse_request":
        await request_movie_prompt(query)
    
    elif data == "browse_upload" and role in ['admin', 'agent']:
        context.user_data.clear()
        context.user_data['upload_mode'] = True
        context.user_data['upload_step'] = 'title'
        context.user_data['movie_data'] = {}
        await upload_step_title(query)
    
    elif data == "browse_agents" and role == 'admin':
        await manage_agents_menu(query)
    
    elif data == "browse_stats" and role == 'admin':
        await show_stats(query)
    
    # আপলোড রিলেটেড
    elif data == "confirm_upload":
        await confirm_upload(query, context)
    
    elif data == "cancel_upload":
        context.user_data.clear()
        await query.edit_message_text("❌ আপলোড বাতিল হয়েছে!", parse_mode='Markdown')
        await start_callback(query, user_id)
    
    elif data == "skip_thumbnail":
        context.user_data['skip_thumbnail'] = True
        context.user_data['upload_step'] = 'summary'
        await upload_show_summary(query, context)
    
    elif data == "add_thumbnail":
        context.user_data['upload_step'] = 'thumbnail'
        await query.edit_message_text(
            "🖼️ *এখন থাম্বনেল ছবি পাঠান:*\n\n"
            "একটি ছবি (JPEG/PNG) পাঠান অথবা /cancel লিখে বাতিল করুন।",
            parse_mode='Markdown'
        )
    
    elif data == "show_summary_after_photo":
        await upload_show_summary(query, context)
    
    # মুভি ডিটেলস
    elif data.startswith("movie_"):
        movie_id = int(data.split("_")[1])
        await show_movie_details(query, movie_id, context.bot)
    
    # এজেন্ট ম্যানেজমেন্ট
    elif data == "agent_add_prompt":
        await add_agent_prompt(query)
    
    elif data == "agent_remove_menu":
        await remove_agent_menu(query)
    
    elif data == "agent_list":
        await show_agent_list(query)
    
    elif data.startswith("confirm_delete_agent_"):
        agent_id = int(data.split("_")[3])
        await confirm_delete_agent(query, agent_id)
    
    elif data.startswith("delete_agent_now_"):
        agent_id = int(data.split("_")[3])
        db.remove_agent(agent_id)
        await query.edit_message_text(f"✅ এজেন্ট `{agent_id}` সফলভাবে রিমুভ করা হয়েছে!", parse_mode='Markdown')
        await manage_agents_menu(query)
    
    elif data == "cancel_delete_agent":
        await manage_agents_menu(query)
    
    # রিকোয়েস্ট
    elif data == "my_requests":
        await show_my_requests(query, user_id)
    
    # মুভি ডিলিট
    elif data.startswith("delete_movie_") and role == 'admin':
        movie_id = int(data.split("_")[2])
        db.delete_movie(movie_id)
        await query.edit_message_text(f"✅ মুভি `{movie_id}` ডিলিট করা হয়েছে!", parse_mode='Markdown')
        await show_latest(query)
    
    # যদি কোন ক্যালব্যাক ম্যাচ না করে
    else:
        await query.edit_message_text("❓ দয়া করে মেইন মেনু থেকে পছন্দ করুন", parse_mode='Markdown')
        await start_callback(query, user_id)

async def start_callback(query, user_id):
    role = db.get_user_role(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🔍 মুভি সার্চ", callback_data="browse_search")],
        [InlineKeyboardButton("📥 নতুন মুভি", callback_data="browse_latest")],
        [InlineKeyboardButton("📝 মুভি রিকোয়েস্ট", callback_data="browse_request")]
    ]
    
    if role in ['admin', 'agent']:
        keyboard.append([InlineKeyboardButton("📤 মুভি আপলোড", callback_data="browse_upload")])
    
    if role == 'admin':
        keyboard.append([
            InlineKeyboardButton("👥 এজেন্ট ম্যানেজ", callback_data="browse_agents"),
            InlineKeyboardButton("📊 স্ট্যাটস", callback_data="browse_stats")
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
        movie_id, title, year, quality, language, size, link, thumbnail, uploader, date = movie
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

async def show_movie_details(query, movie_id, bot):
    movie = db.get_movie_by_id(movie_id)
    
    if not movie:
        await query.edit_message_text("❌ মুভি পাওয়া যায়নি!", parse_mode='Markdown')
        return
    
    movie_id, title, year, quality, language, size, link, thumbnail, uploader, date = movie
    
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
        [InlineKeyboardButton("🔙 নতুন মুভি", callback_data="browse_latest")]
    ]
    
    # অ্যাডমিন হলে ডিলিট বাটন
    user_id = query.from_user.id
    role = db.get_user_role(user_id)
    if role == 'admin':
        keyboard.append([InlineKeyboardButton("🗑️ মুভি ডিলিট", callback_data=f"delete_movie_{movie_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # যদি থাম্বনেল থাকে
    if thumbnail:
        try:
            await bot.send_photo(
                chat_id=query.message.chat_id,
                photo=thumbnail,
                caption=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            await query.delete_message()
        except Exception as e:
            print(f"Error sending photo: {e}")
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
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

async def upload_show_summary(query, context):
    movie_data = context.user_data.get('movie_data', {})
    thumbnail = context.user_data.get('thumbnail', '')
    
    has_thumbnail = bool(thumbnail)
    thumbnail_status = "✅ আছে" if has_thumbnail else "❌ নেই"
    
    text = f"""
📋 *আপলোড সামারি*

🎬 *নাম:* {movie_data.get('title', 'N/A')}
📅 *সাল:* {movie_data.get('year', 'N/A')}
⚡ *কোয়ালিটি:* {movie_data.get('quality', 'N/A')}
🗣️ *ভাষা:* {movie_data.get('language', 'N/A')}
💾 *সাইজ:* {movie_data.get('size', 'N/A')}
🖼️ *থাম্বনেল:* {thumbnail_status}
🔗 *লিংক:* {movie_data.get('link', 'N/A')[:50]}...

✅ সবকিছু ঠিক আছে?
"""
    
    keyboard = [
        [InlineKeyboardButton("✅ আপলোড করুণ", callback_data="confirm_upload")],
    ]
    
    if not has_thumbnail:
        keyboard.append([InlineKeyboardButton("🖼️ থাম্বনেল যোগ করুন", callback_data="add_thumbnail")])
    
    keyboard.append([InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def confirm_upload(query, context):
    user_id = query.from_user.id
    movie_data = context.user_data.get('movie_data', {})
    thumbnail = context.user_data.get('thumbnail', '')
    
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
            'thumbnail': thumbnail,
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
🖼️ *থাম্বনেল:* {'✅ আছে' if thumbnail else '❌ নেই'}

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
    agents = db.get_agents_with_details()
    
    text = "👥 *এজেন্ট ম্যানেজমেন্ট*\n\n"
    
    if agents:
        text += "📋 *সক্রিয় এজেন্ট লিস্ট:*\n"
        for agent_id, username, added_date in agents:
            username_display = f"@{username}" if username else "No Username"
            text += f"• `{agent_id}` - {username_display}\n"
        text += f"\n💰 মোট এজেন্ট: {len(agents)}"
    else:
        text += "📭 *কোন এজেন্ট নেই*"
    
    keyboard = [
        [InlineKeyboardButton("➕ নতুন এজেন্ট অ্যাড", callback_data="agent_add_prompt")],
        [InlineKeyboardButton("➖ এজেন্ট রিমুভ", callback_data="agent_remove_menu")],
        [InlineKeyboardButton("📋 এজেন্ট লিস্ট", callback_data="agent_list")],
        [InlineKeyboardButton("🔙 হোম", callback_data="home")]
    ]
    
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

async def show_agent_list(query):
    agents = db.get_agents_with_details()
    
    if not agents:
        await query.edit_message_text("📭 কোন এজেন্ট নেই!", parse_mode='Markdown')
        return
    
    text = "📋 *এজেন্ট লিস্ট:*\n\n"
    
    for agent_id, username, added_date in agents:
        username_display = f"@{username}" if username else "No Username"
        text += f"🆔 *ID:* `{agent_id}`\n"
        text += f"👤 *Username:* {username_display}\n"
        text += f"📅 *যোগ দেওয়ার তারিখ:* {added_date[:10] if added_date else 'N/A'}\n"
        text += "─" * 20 + "\n"
    
    text += f"\n💰 *মোট এজেন্ট:* {len(agents)}"
    
    keyboard = [
        [InlineKeyboardButton("➖ এজেন্ট রিমুভ", callback_data="agent_remove_menu")],
        [InlineKeyboardButton("🔙 এজেন্ট ম্যানেজ", callback_data="browse_agents")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def remove_agent_menu(query):
    agents = db.get_agents_with_details()
    
    if not agents:
        await query.edit_message_text("📭 কোন এজেন্ট নেই রিমুভ করার!", parse_mode='Markdown')
        return
    
    text = "➖ *এজেন্ট রিমুভ মেনু*\n\n"
    text += "নিচের এজেন্ট থেকে সিলেক্ট করুন:\n\n"
    
    keyboard = []
    
    for agent_id, username, added_date in agents[:10]:
        username_display = f"@{username}" if username else "No Username"
        button_text = f"❌ {agent_id} - {username_display}"
        if len(button_text) > 50:
            button_text = f"❌ {agent_id}"
        
        keyboard.append([InlineKeyboardButton(
            button_text, 
            callback_data=f"confirm_delete_agent_{agent_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 এজেন্ট ম্যানেজ", callback_data="browse_agents")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def confirm_delete_agent(query, agent_id):
    agents = db.get_agents_with_details()
    agent_info = None
    
    for agent in agents:
        if agent[0] == agent_id:
            agent_info = agent
            break
    
    if not agent_info:
        await query.edit_message_text("❌ এজেন্ট পাওয়া যায়নি!", parse_mode='Markdown')
        return
    
    agent_id, username, added_date = agent_info
    username_display = f"@{username}" if username else "No Username"
    
    text = f"""
⚠️ *এজেন্ট রিমুভ কনফার্মেশন*

🆔 *এজেন্ট ID:* `{agent_id}`
👤 *Username:* {username_display}
📅 *যোগ দেওয়ার তারিখ:* {added_date[:10] if added_date else 'N/A'}

❓ আপনি কি নিশ্চিত এই এজেন্টকে রিমুভ করতে চান?
"""
    
    keyboard = [
        [InlineKeyboardButton("✅ হ্যাঁ, রিমুভ করুণ", callback_data=f"delete_agent_now_{agent_id}")],
        [InlineKeyboardButton("❌ না, বাতিল করুণ", callback_data="cancel_delete_agent")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

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
    
    for req in requests[:10]:
        req_id, user_id, movie_name, date, status = req
        status_icon = "⏳" if status == "pending" else "✅" if status == "completed" else "❌"
        text += f"{status_icon} *{movie_name}*\n"
        text += f"   📅 {date[:10]} | Status: {status}\n\n"
    
    text += f"\n💰 মোট রিকোয়েস্ট: {len(requests)}"
    
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
    message_text = update.message.text.strip() if update.message.text else ""
    role = db.get_user_role(user_id)
    
    print(f"Message from {user_id}: {message_text[:50]}...")
    
    # ১. যদি ফটো মেসেজ (থাম্বনেল)
    if update.message.photo and context.user_data.get('upload_mode'):
        await handle_thumbnail_photo(update, context)
        return
    
    # ২. কমান্ড হ্যান্ডলিং
    if message_text.startswith('/'):
        if message_text.startswith('/cancel'):
            context.user_data.clear()
            await update.message.reply_text("❌ অপারেশন বাতিল হয়েছে!", parse_mode='Markdown')
            return
    
    # ৩. যদি আপলোড মোডে থাকে (টেক্সট)
    if context.user_data.get('upload_mode'):
        await handle_upload_message(update, context)
        return
    
    # ৪. যদি অ্যাডমিন এজেন্ট আইডি পাঠায় (সাধারণ মেসেজ হিসেবে)
    if role == 'admin' and message_text.isdigit():
        agent_id = int(message_text)
        success = db.add_agent(agent_id, user_id)
        if success:
            await update.message.reply_text(f"✅ এজেন্ট `{agent_id}` সফলভাবে অ্যাড করা হয়েছে!", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ এজেন্ট অ্যাড করতে সমস্যা!", parse_mode='Markdown')
        return
    
    # ৫. যদি মুভি সার্চ/রিকোয়েস্ট হয়
    if len(message_text) > 1:
        # প্রথমে সার্চ করুন
        movies = db.search_movies(message_text)
        
        if movies:
            # মুভি পাওয়া গেছে
            text = f"🔍 *'{message_text}' এর রেজাল্ট:*\n\n"
            keyboard = []
            
            for movie in movies[:5]:
                movie_id, title, year, quality, language, size, link, thumbnail, uploader, date = movie
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
    
    # ৬. ডিফল্ট রেসপন্স
    await update.message.reply_text("✉️ মেসেজ রিসিভ হয়েছে!", parse_mode='Markdown')

async def handle_thumbnail_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """থাম্বনেল ফটো হ্যান্ডলার"""
    user_id = update.effective_user.id
    step = context.user_data.get('upload_step', '')
    
    print(f"Thumbnail photo received, step: {step}")
    
    if step == 'thumbnail':
        # সর্বোচ্চ রেজোলিউশনের ফটো নিন
        photo = update.message.photo[-1]
        file_id = photo.file_id
        
        # থাম্বনেল সেভ করুন
        context.user_data['thumbnail'] = file_id
        context.user_data['upload_step'] = 'summary'
        
        await update.message.reply_text(
            "✅ থাম্বনেল সফলভাবে সেভ হয়েছে!\n\n"
            "আপলোড সামারি দেখতে প্রস্তুত...",
            parse_mode='Markdown'
        )
        
        # সামারি শো করান
        keyboard = [[InlineKeyboardButton("📋 সামারি দেখুন", callback_data="show_summary_after_photo")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "নিচের বাটনে ক্লিক করে আপলোড সামারি দেখুন:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ এখন থাম্বনেল আপলোডের সময় নয়!", parse_mode='Markdown')

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
        await update.message.reply_text(
            f"✅ নাম সেভ হয়েছে: *{message_text}*\n\n"
            "📅 *এখন মুভির সাল লিখুন:*\n"
            "উদাহরণ: 2023, 2022, 2021",
            parse_mode='Markdown'
        )
    
    elif step == 'year':
        movie_data['year'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'quality'
        await update.message.reply_text(
            f"✅ সাল সেভ হয়েছে: *{message_text}*\n\n"
            "⚡ *এখন ভিডিও কোয়ালিটি লিখুন:*\n"
            "উদাহরণ: 1080p WEB-DL, 720p HDRip",
            parse_mode='Markdown'
        )
    
    elif step == 'quality':
        movie_data['quality'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'language'
        await update.message.reply_text(
            f"✅ কোয়ালিটি সেভ হয়েছে: *{message_text}*\n\n"
            "🗣️ *এখন ভাষা লিখুন:*\n"
            "উদাহরণ: বাংলা ডাবিং, বাংলা সাবটাইটেল",
            parse_mode='Markdown'
        )
    
    elif step == 'language':
        movie_data['language'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'size'
        await update.message.reply_text(
            f"✅ ভাষা সেভ হয়েছে: *{message_text}*\n\n"
            "💾 *এখন ফাইল সাইজ লিখুন:*\n"
            "উদাহরণ: 1.5GB, 2.3GB, 850MB",
            parse_mode='Markdown'
        )
    
    elif step == 'size':
        movie_data['size'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'link'
        await update.message.reply_text(
            f"✅ সাইজ সেভ হয়েছে: *{message_text}*\n\n"
            "🔗 *এখন ডাউনলোড লিংক দিন:*\n"
            "উদাহরণ: https://drive.google.com/...\n\n"
            "⚠️ ভ্যালিড লিংক দিন!",
            parse_mode='Markdown'
        )
    
    elif step == 'link':
        # লিংক ভ্যালিডেশন
        if not message_text.startswith(('http://', 'https://')):
            await update.message.reply_text(
                "❌ ভ্যালিড HTTP/HTTPS লিংক দিন!\n"
                "উদাহরণ: https://drive.google.com/file/...",
                parse_mode='Markdown'
            )
            return
        
        movie_data['link'] = message_text
        context.user_data['movie_data'] = movie_data
        context.user_data['upload_step'] = 'thumbnail'
        
        keyboard = [
            [InlineKeyboardButton("⏭️ থাম্বনেল ছাড়া কন্টিনিউ", callback_data="skip_thumbnail")],
            [InlineKeyboardButton("❌ বাতিল", callback_data="cancel_upload")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ লিংক সেভ হয়েছে!\n\n"
            "🖼️ *এখন থাম্বনেল আপলোড করুন:*\n\n"
            "1. একটি ছবি পাঠান (JPEG/PNG)\n"
            "2. অথবা থাম্বনেল ছাড়াই কন্টিনিউ করুন",
            parse_mode='Markdown'
        )

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
    application.add_handler(CommandHandler("agents", show_agents_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # বাটন হ্যান্ডলার
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # মেসেজ হ্যান্ডলার (টেক্সট + ফটো)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_message
    ))
    application.add_handler(MessageHandler(
        filters.PHOTO,
        handle_message
    ))
    
    # বট শুরু
    print("=" * 50)
    print("✅ Movie Bot চালু হয়েছে! (থাম্বনেল ফিক্সড)")
    print(f"🔑 Admin ID: 5347353883")
    print("📱 Telegram এ যান এবং বটে /start দিন")
    print("=" * 50)
    print("🎬 মুভি আপলোড: কাজ করবে")
    print("🖼️ থাম্বনেল: কাজ করবে")
    print("👥 এজেন্ট ম্যানেজ: কাজ করবে")
    print("🔍 সার্চ: কাজ করবে")
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

async def show_agents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_user_role(user_id)
    
    if role != 'admin':
        await update.message.reply_text("❌ আপনার অ্যাডমিন এক্সেস নেই!", parse_mode='Markdown')
        return
    
    agents = db.get_agents_with_details()
    
    if not agents:
        await update.message.reply_text("📭 কোন এজেন্ট নেই!", parse_mode='Markdown')
        return
    
    text = "📋 *এজেন্ট লিস্ট:*\n\n"
    
    for agent_id, username, added_date in agents:
        username_display = f"@{username}" if username else "No Username"
        text += f"🆔 *ID:* `{agent_id}`\n"
        text += f"👤 *Username:* {username_display}\n"
        text += f"📅 *যোগ দেওয়ার তারিখ:* {added_date[:10] if added_date else 'N/A'}\n"
        text += "─" * 20 + "\n"
    
    text += f"\n💰 *মোট এজেন্ট:* {len(agents)}"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ সব অপারেশন ক্লিয়ার হয়েছে!", parse_mode='Markdown')

if __name__ == '__main__':
    main()
