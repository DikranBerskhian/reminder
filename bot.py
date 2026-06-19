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
# The script checks Render's dashboard environment variables first.
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    # WRITE YOUR BOT_TOKEN FROM BOTFATHER BETWEEN THE QUOTES BELOW:
    BOT_TOKEN = '8587366883:AAEXXN_HmvzXgydmwTBsvw9DV7KKINQUPpg'

bot = telebot.TeleBot(BOT_TOKEN)

# ==============================================================================
# 2. AIVEN CLOUD DATABASE API CONFIGURATION
# ==============================================================================
# The script checks Render's dashboard environment variables first.
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    # WRITE YOUR SERVICE URI FROM AIVEN BETWEEN THE QUOTES BELOW (Optional for local testing):
    # Example: 'postgres://avnadmin:password@host:port/defaultdb?sslmode=require'
    DATABASE_URL = '' 

# If a database URL is present (either from Render or hardcoded above), configure it
if DATABASE_URL:
    # Fix for SQLAlchemy compatibility (forces postgresql:// instead of postgres://)
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    jobstores = {
        'default': SQLAlchemyJobStore(url=DATABASE_URL)
    }
else:
    # Fallback to local file if no cloud database string is found anywhere
    print("⚠️ No Cloud Database URL found. Saving reminders to local reminders.db file.")
    jobstores = {
        'default': SQLAlchemyJobStore(url='sqlite:///reminders.db')
    }

# Initialize background scheduler clock and link the database
local_tz = tzlocal.get_localzone()
scheduler = BackgroundScheduler(jobstores=jobstores, timezone=local_tz)
scheduler.start()

# ==============================================================================
# 3. BOT ACTIONS & LOGIC
# ==============================================================================
def send_reminder(chat_id, event_name, event_time_str):
    """Triggers automatically when the background timer hits the 5-hour mark."""
    try:
        reminder_text = (
            f"⏰ **Reminder!**\n\n"
            f"Your event *'{event_name}'* is happening in exactly 5 hours!\n"
            f"📅 **Event Time:** {event_time_str}"
        )
        bot.send_message(chat_id, reminder_text, parse_mode='Markdown')
    except Exception as e:
        print(f"Error sending scheduled alert: {e}")

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
        # Clean text line breaks and remove text platform artifacts
        raw_text = message.text.encode('ascii', 'ignore').decode('ascii').replace('\n', ' ').replace('\r', ' ').strip()
        if raw_text.upper().startswith("EVENT"): 
            raw_text = raw_text[5:].strip()
            
        # Parse the text to extract the date/time string from the tail end
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})\s*\|?\s*(\d{2}):(\d{2})\s*$', raw_text)
        if not match:
            bot.reply_to(message, "❌ **Format error!** Use format:\n`Event Name | YYYY-MM-DD HH:MM`")
            return
            
        year, month, day, hour, minute = map(int, match.groups())
        event_name = raw_text[:match.start()].strip().rstrip('|').strip() or "Untitled Event"

        # Apply native timezone settings
        event_time = datetime(year, month, day, hour, minute).replace(tzinfo=local_tz)
        current_time = datetime.now(local_tz)
        reminder_time = event_time - timedelta(hours=5)
        
        # Guard configurations
        if event_time <= current_time:
            bot.reply_to(message, "❌ That event time is already in the past!")
            return
        if reminder_time <= current_time:
            bot.reply_to(message, f"⚠️ This event takes place in less than 5 hours!")
            return

        # Unique key index for database rows
        job_id = f"{message.chat.id}_{int(event_time.timestamp())}"
        
        # Add the job entry into the relational database engine
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

# Run continuous long-polling server loops
if __name__ == '__main__':
    bot.infinity_polling()