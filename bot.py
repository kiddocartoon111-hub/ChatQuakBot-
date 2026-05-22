import sqlite3
import requests
import time
import random
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = "YOUR_BOT_TOKEN"
GROQ_API_KEY = "YOUR_GROQ_API_KEY"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ========== DATABASE SETUP (Optimized) ==========
def init_db():
    conn = sqlite3.connect('chatquake.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  group_id INTEGER,
                  user_id INTEGER,
                  username TEXT,
                  text TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    # Fast search ke liye index
    c.execute("CREATE INDEX IF NOT EXISTS idx_group_user ON messages (group_id, user_id)")
    conn.commit()
    conn.close()

def store_message(group_id, user_id, username, text):
    conn = sqlite3.connect('chatquake.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT INTO messages (group_id, user_id, username, text) VALUES (?,?,?,?)",
              (group_id, user_id, username, text))
    conn.commit()
    conn.close()

def get_user_messages(group_id, user_id, limit=100):
    conn = sqlite3.connect('chatquake.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT text FROM messages WHERE group_id=? AND user_id=? ORDER BY timestamp DESC LIMIT ?",
              (group_id, user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def cleanup_old_messages(group_id, keep=500):
    """Har group ke sirf latest `keep` messages rakhta hai, baaki delete"""
    conn = sqlite3.connect('chatquake.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE group_id=? AND id NOT IN (SELECT id FROM messages WHERE group_id=? ORDER BY timestamp DESC LIMIT ?)",
              (group_id, group_id, keep))
    conn.commit()
    conn.close()

# ========== CACHING + RATE LIMIT ==========
# (group_id, user_id) -> (roast_text, timestamp)
roast_cache = {}
# rate limit: per user per group, cooldown 2 minutes
last_expose = {}  # key: (group_id, user_id) -> timestamp

def is_rate_limited(group_id, user_id, cooldown=120):
    key = (group_id, user_id)
    now = time.time()
    if key in last_expose and (now - last_expose[key]) < cooldown:
        return True
    last_expose[key] = now
    return False

# ========== ROAST GENERATION (VARIED, HINGLISH) ==========
def generate_roast(username, messages):
    if not messages:
        return f"👀 @{username} ne toh abhi tak kuch nahi bola... thoda active ho jao, phir roast karenge."

    # Last 30 messages use karo
    recent = messages[:30]
    chat_data = "\n".join(recent)

    # Random style select karo taaki har baar alag lage
    style = random.choice([
        "funny news report",
        "shayari style",
        "dialogue like a movie villain",
        "exaggerated comparison (e.g., 'ye banda world record holder hai...')",
        "roasting as a professor giving marks",
        "stand-up comedy style",
        "sarcastic praise (taarif karte hue roast)",
        "fake prediction (bhavishyavani style)"
    ])

    prompt = f"""You are a Hinglish roast master, expert in creating funny, unique, and slightly savage roasts based on a person's Telegram chat history.
You will be given the last few messages of @{username} from a group.
Your task: analyze the messages carefully, pick specific phrases, words, habits, timing, topics they talk about, and then write a ROAST in Hinglish (Hindi + English mix).
The roast MUST be:
- **100% unique every time** (never repeat the same joke/insult)
- **Based on real data** from their messages (e.g., "tu roz subah 2 baje hi kyu aata hai?")
- **Creative and engaging** – use the chosen style: "{style}"
- **Mildly teasing, not cruel or abusive** (friendly roasting)
- **Around 3-5 lines** (no lengthy paragraphs)
- **Include @{username} in the roast**
- **Only output the roast, no explanations, no prefix.**

Here are the messages:
---
{chat_data}
---

Now write the roast in Hinglish using the "{style}" style. Be funny and specific!"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.95,
        "max_tokens": 250,
        "top_p": 0.9
    }

    try:
        resp = requests.post(GROQ_URL, headers=headers, json=payload)
        if resp.status_code == 200:
            roast = resp.json()["choices"][0]["message"]["content"].strip()
            # Fallback if empty
            if not roast:
                return f"@{username} ke messages padh liye, lekin aaj AI chup hai... shayad itne boring messages the ki roast bhi so gaya 😴"
            return roast
        else:
            return "⚠️ AI bhai ne kaam karna band kar diya, thodi der baad try karo."
    except Exception as e:
        return f"⚠️ Error: {e}"

# ========== BOT HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 **ChatQuakeBot** zinda hai!\n"
        "• Group mein add karo aur admin banao.\n"
        "• Privacy mode **DISABLE** karo (BotFather se).\n"
        "• Phir `/expose @username` karo roast ke liye.\n"
        "• Pehle thoda chat hone do, fir roast solid banega.\n\n"
        "⚠️ Spam se bacho – ek user per 2 minute mein sirf 1 roast."
    )

async def store_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    # sirf group/supergroup ke text messages store karo
    if msg.chat.type in ["group", "supergroup"] and msg.text and not msg.text.startswith('/'):
        store_message(
            msg.chat.id,
            msg.from_user.id,
            msg.from_user.username or msg.from_user.first_name,
            msg.text
        )
        # Har 50 messages ke baad cleanup (optional, performance ke liye)
        if random.randint(1, 50) == 1:
            cleanup_old_messages(msg.chat.id)

async def expose_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    group_id = msg.chat.id
    
    # --- Determine target user ---
    if msg.reply_to_message:
        target = msg.reply_to_message.from_user
    elif context.args and context.args[0].startswith('@'):
        username = context.args[0].lstrip('@')
        # username se user_id nikaalna DB se
        conn = sqlite3.connect('chatquake.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT user_id FROM messages WHERE group_id=? AND username=? ORDER BY timestamp DESC LIMIT 1",
                  (group_id, username))
        row = c.fetchone()
        conn.close()
        if not row:
            await msg.reply_text(f"❌ @{username} ka koi message nahi mila is group mein. Pehle bolne do.")
            return
        target_id = row[0]
        target_username = username
    else:
        await msg.reply_text("⚠️ Use: /expose @username (ya kisi message ke reply mein /expose)")
        return

    # Agar reply se aaya to id aur username set karo
    if msg.reply_to_message:
        target_id = target.id
        target_username = target.username or target.first_name
    else:
        # Pehle se target_id set hai
        pass

    # Rate limit check
    if is_rate_limited(group_id, target_id):
        await msg.reply_text("⏳ Bhai, thoda ruk ja. Har 2 minute mein ek hi roast allowed hai.")
        return

    # Cache check
    cache_key = (group_id, target_id)
    now = time.time()
    if cache_key in roast_cache and (now - roast_cache[cache_key][1]) < 300:  # 5 min cache
        await msg.reply_text(roast_cache[cache_key][0])
        return

    # Messages fetch karo
    messages = get_user_messages(group_id, target_id, 100)
    if not messages:
        await msg.reply_text(f"🤷‍♂️ @{target_username} ne abhi tak kuch nahi bola, ya messages store nahi hue. Thodi der baad try karo.")
        return

    # Roast generate karo
    roast = generate_roast(target_username, messages)
    # Cache mein save karo
    roast_cache[cache_key] = (roast, now)

    await msg.reply_text(roast)

# ========== MAIN ==========
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("expose", expose_user))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, store_msg))

    print("ChatQuakeBot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
