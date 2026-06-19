import os
import re
import telebot
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import tzlocal

# ==============================================================================
# 1. TELEGRAM BOT API CONFIGURATION
# ==============================================================================
# Render reads this dynamically from the environment variables you set in its dashboard
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    # If testing locally on your laptop and variable isn't set, it uses this fallback
    BOT_TOKEN = '8587366883:AAEXXN_HmvzXgydmwTBsvw9DV7KKINQUPpg'

bot = telebot.TeleBot(BOT_TOKEN)

# ==============================================================================
# 2. AIVEN CLOUD DATABASE API CONFIGURATION
# ==============================================================================
# Render reads your Aiven Service URI string dynamically from your dashboard config
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # Safe routing fix: updates 'postgres://' to 'postgresql://' for SQLAlchemy compatibility
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    # Direct configuration for psycopg2 driver architecture
    connect_args = {
        "sslmode": "require"
    }
    
    jobstores = {
        'default': SQLAlchemyJobStore(url=DATABASE_URL, engine_options={"connect_args": connect_args})
    }
else:
    # Fallback storage backup if running purely locally without cloud connection variables
    print("⚠️ DATABASE_URL environment variable missing. Defaulting to local SQLite engine.")
    jobstores = {
        'default': SQLAlchemyJobStore(url='sqlite:///reminders.db')
    }

# Dynamic local timezone parsing engine
local_tz = tzlocal.get_localzone()
scheduler = BackgroundScheduler(jobstores=jobstores, timezone=local_tz)

# Instructs the database connection to auto-generate rows and setup schemas if blank
scheduler.start()

# ==============================================================================
# 3. BOT ACTIONS & LOGIC
# ==============================================================================
def send_reminder(chat_id, event_name, event_time_str):
    """Executes background callback task when the event clock ticks to T-minus 5 hours."""
    try:
        reminder_text = (
            f"⏰ **Reminder!**\n\n"
            f"Your event *'{event_name}'* is happening in exactly 5 hours!\n"
            f"📅 **Event Time:** {event_time_str}"
        )
        bot.send_message(chat_id, reminder_text, parse_mode='Markdown')
    except Exception as e:
        print(f"Error distributing cloud notification update packet: {e}")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "👋 Welcome! Send me your events, and I will remind you exactly 5 hours before they start.\n\n"
        "**Format:**\n"
        "`Event Name | YYYY-MM-DD HH:MM`"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_event(message):
    try:
        # Sanitize message line endings across different user operating systems
        raw_text = message.text.encode('ascii', 'ignore').decode('ascii').replace('\n', ' ').replace('\r', ' ').strip()
        if raw_text.upper().startswith("EVENT"): 
            raw_text = raw_text[5:].strip()
            
        # Parse text logic to clip date format strings from data segments
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})\s*\|?\s*(\d{2}):(\d{2})\s*$', raw_text)
        if not match:
            bot.reply_to(message, "❌ **Format error!** Use format:\n`Event Name | YYYY-MM-DD HH:MM`")
            return
            
        year, month, day, hour, minute = map(int, match.groups())
        event_name = raw_text[:match.start()].strip().rstrip('|').strip() or "Untitled Event"

        # Apply specific native timezone transformations
        event_time = datetime(year, month, day, hour, minute).replace(tzinfo=local_tz)
        current_time = datetime.now(local_tz)
        reminder_time = event_time - timedelta(hours=5)
        
        # Scheduling validations
        if event_time <= current_time:
            bot.reply_to(message, "❌ That event time is already in the past!")
            return
        if reminder_time <= current_time:
            bot.reply_to(message, f"⚠️ This event takes place in less than 5 hours!")
            return

        # Unique identifier creation key for task engine reference indices
        job_id = f"{message.chat.id}_{int(event_time.timestamp())}"
        
        # Commit background scheduler updates to cloud relational tables via engine connection
        scheduler.add_job(
            send_reminder, 
            'date', 
            run_date=reminder_time, 
            args=[message.chat.id, event_name, event_time.strftime('%Y-%m-%d %H:%M')], 
            id=job_id, 
            replace_existing=True
        )
        
        success_message = (
            f"✅ **Event Registered Successfully!**\n\n"
            f"🎬 **Event:** {event_name}\n"
            f"📅 **Time:** {event_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"🔔 **Reminder Set For:** {reminder_time.strftime('%Y-%m-%d %H:%M')}"
        )
        bot.reply_to(message, success_message, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ **Internal Error:** {str(e)}")

if __name__ == '__main__':
    print("Cloud system configuration initialized. Deploying long-polling background runner listener...")
    bot.infinity_polling()