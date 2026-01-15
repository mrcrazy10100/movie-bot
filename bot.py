import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import sqlite3
from datetime import datetime

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('movies.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'user',
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
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
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS agents (
                agent_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.cursor.execute('INSERT OR IGNORE INTO users (user_id, role) VALUES (?, ?)', (5347353883, 'admin'))
        self.conn.commit()
    
    def get_user_role(self, user_id):
        self.cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result: return result[0]
        self.cursor.execute('INSERT INTO users (user_id, role) VALUES (?, ?)', (user_id, 'user'))
        self.conn.commit()
        return 'user'
    
    def add_movie(self, data):
        self.cursor.execute('INSERT INTO movies (title, year, quality, language, size, download_link, uploader_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (data['title'], data['year'], data['quality'], data['language'], data['size'], data['download_link'], data['uploader_id']))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_movies(self, limit=10):
        self.cursor.execute('SELECT * FROM movies ORDER BY id DESC LIMIT ?', (limit,))
        return self.cursor.fetchall()
    
    def get_agents(self):
        self.cursor.execute('SELECT agent_id FROM agents')
        return [row[0] for row in self.cursor.fetchall()]
    
    def add_agent(self, agent_id, admin_id):
        self.cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (agent_id,))
        self.cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', ('agent', agent_id))
        self.cursor.execute('INSERT OR REPLACE INTO agents (agent_id, added_by) VALUES (?, ?)', (agent_id, admin_id))
        self.conn.commit()
    
    def remove_agent(self, agent_id):
        self.cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', ('user', agent_id))
        self.cursor.execute('DELETE FROM agents WHERE agent_id = ?', (agent_id,))
        self.conn.commit()
    
    def get_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM users')
        users = self.cursor.fetchone()[0]
        self.cursor.execute('SELECT COUNT(*) FROM movies')
        movies = self.cursor.fetchone()[0]
        self.cursor.execute('SELECT COUNT(*) FROM agents')
        agents = self.cursor.fetchone()[0]
        return {'users': users, 'movies': movies, 'agents': agents}

db = Database()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = db.get_user_role(user_id)
    
    welcome_text = """🎬 *Welcome to Movie Share Bot!* 🍿

নিচের বাটনগুলো ব্যবহার করুন:"""
    
    keyboard = [
        [InlineKeyboardButton("🔍 মুভি সার্চ", callback_data="search")],
        [InlineKeyboardButton("📥 নতুন মুভি", callback_data="latest")],
        [InlineKeyboardButton("📝 রিকোয়েস্ট", callback_data="request")]
    ]
    
    if role in ['admin', 'agent']:
        keyboard.append([InlineKeyboardButton("📤 মুভি আপলোড", callback_data="upload")])
    
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
    
    if query.data == "latest":
        await show_latest(query)
    elif query.data == "upload" and role in ['admin', 'agent']:
        await upload_movie_prompt(query)
    elif query.data == "manage_agents" and role == 'admin':
        await manage_agents_menu(query)
    elif query.data == "stats" and role == 'admin':
        await show_stats(query)
    elif query.data == "back_home":
        await start_callback(query)
    elif query.data.startswith("movie_"):
        movie_id = int(query.data.split("_")[1])
        await show_movie_details(query, movie_id, context)
    elif query.data.startswith("del_agent_"):
        agent_id = int(query.data.split("_")[2])
        db.remove_agent(agent_id)
        await query.edit_message_text(f"✅ এজেন্ট {agent_id} রিমুভ করা হয়েছে!")

async def start_callback(query):
    user_id = query.from_user.id
    role = db.get_user_role(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🔍 মুভি সার্চ", callback_data="search")],
        [InlineKeyboardButton("📥 নতুন মুভি", callback_data="latest")],
        [InlineKeyboardButton("📝 রিকোয়েস্ট", callback_data="request")]
    ]
    
    if role in ['admin', 'agent']:
        keyboard.append([InlineKeyboardButton("📤 মুভি আপলোড", callback_data="upload")])
    
    if role == 'admin':
        keyboard.append([
            InlineKeyboardButton("👥 এজেন্ট ম্যানেজ", callback_data="manage_agents"),
            InlineKeyboardButton("📊 স্ট্যাটস", callback_data="stats")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🏠 *মেইন মেনু*", reply_markup=reply_markup, parse_mode='Markdown')

async def show_latest(query):
    movies = db.get_movies(5)
    
    if not movies:
        await query.edit_message_text("📭 এখনো কোন মুভি নেই!")
        return
    
    text = "📥 *নতুন মুভি:*\n\n"
    keyboard = []
    
    for movie in movies:
        text += f"🎬 {movie[1]}\n"
        keyboard.append([InlineKeyboardButton(f"🎬 {movie[1][:20]}...", callback_data=f"movie_{movie[0]}")])
    
    keyboard.append([InlineKeyboardButton("🔙 হোম", callback_data="back_home")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_movie_details(query, movie_id, context):
    db.cursor.execute('SELECT * FROM movies WHERE id = ?', (movie_id,))
    movie = db.cursor.fetchone()
    
    if not movie:
        await query.edit_message_text("❌ মুভি পাওয়া যায়নি!")
        return
    
    text = f"""🎬 *{movie[1]}* ({movie[2]})

⚡ {movie[3]}
🗣️ {movie[4]}
💾 {movie[5]}

📥 লিংক:
{movie[6]}"""
    
    keyboard = [[InlineKeyboardButton("🔙 পিছনে", callback_data="latest")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def upload_movie_prompt(query):
    await query.edit_message_text("📤 মুভি আপলোড শীঘ্রই আসছে!")

async def manage_agents_menu(query):
    agents = db.get_agents()
    
    text = "👥 *এজেন্ট ম্যানেজমেন্ট*\n\n"
    keyboard = []
    
    if agents:
        text += "এজেন্ট লিস্ট:\n"
        for agent_id in agents:
            text += f"• {agent_id}\n"
            keyboard.append([InlineKeyboardButton(f"❌ {agent_id}", callback_data=f"del_agent_{agent_id}")])
    else:
        text += "কোন এজেন্ট নেই\n"
    
    keyboard.append([InlineKeyboardButton("➕ এজেন্ট অ্যাড", callback_data="add_agent")])
    keyboard.append([InlineKeyboardButton("🔙 হোম", callback_data="back_home")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_stats(query):
    stats = db.get_stats()
    
    text = f"""📊 *স্ট্যাটিস্টিকস*

👥 ইউজার: {stats['users']}
🎬 মুভি: {stats['movies']}
👷 এজেন্ট: {stats['agents']}"""
    
    keyboard = [[InlineKeyboardButton("🔙 হোম", callback_data="back_home")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message.text
    
    if db.get_user_role(user_id) == 'admin' and msg.isdigit():
        agent_id = int(msg)
        db.add_agent(agent_id, user_id)
        await update.message.reply_text(f"✅ এজেন্ট {agent_id} অ্যাড করা হয়েছে!")
        return
    
    await update.message.reply_text("✉️ মেসেজ রিসিভ হয়েছে!")

def main():
    BOT_TOKEN = "5649845146:AAGuL82r0Ib-vN2YkRl2HzqFBZjQtWcjTps"
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot running...")
    application.run_polling()

if __name__ == '__main__':
    main()
