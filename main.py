import sqlite3 as sql
from datetime import datetime
from threading import Thread
import time
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler
import config

bot = telebot.TeleBot(config.BOT_TOKEN)
admin_ids = config.ADMIN_IDS
user_states = {}

def init_db():
    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS birthdays (
        user_id INTEGER PRIMARY KEY,
        user TEXT,
        birthday_date TEXT,
        notification INTEGER DEFAULT 0 NOT NULL
        )""")
        
        c.execute("""CREATE TABLE IF NOT EXISTS photo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL,
            caption TEXT DEFAULT "Нет подписи"
        )""")
        
        c.execute("""CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            is_active INTEGER DEFAULT 1,
            mailing_time TEXT DEFAULT "09:00"
        )""")

init_db()

def add_chat(chat_id, title, mailing_time="09:00"):
    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("INSERT OR IGNORE INTO chats (chat_id, title, mailing_time) VALUES (?, ?, ?)", 
                 (chat_id, title, mailing_time))

def get_chats_for_mailing():
    current_time = datetime.now().strftime(config.TIME_FORMAT)
    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("SELECT chat_id FROM chats WHERE is_active = 1 AND mailing_time = ?", (current_time,))
        return [row[0] for row in c.fetchall()]
        
def update_chat_mailing_time(chat_id, mailing_time):
    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("UPDATE chats SET mailing_time = ? WHERE chat_id = ?", (mailing_time, chat_id))
        
def get_random_photo():
    try:
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("SELECT file_id FROM photo ORDER BY RANDOM() LIMIT 1")
            result = c.fetchone()
            return result[0] if result else None
    except Exception as e:
        print(f"Ошибка при получении фото: {e}")
        
def morning_mailing():
    try:
        today = datetime.now().strftime(config.DATE_FORMAT)
        random_photo = get_random_photo()
        chat_ids = get_chats_for_mailing()
        
        if not chat_ids:
            return
            
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("SELECT user FROM birthdays WHERE substr(birthday_date, 1, 5) = ?", (today,))
            birthdays = [row[0] for row in c.fetchall()]
            
        if birthdays:
            message = "Сегодня день рождения у:\n"
            for user in birthdays:
                message += f"@{user}\n"
            message += "Поздравляем!"
        else:
            message = "Доброе утро!"
            
        for chat_id in chat_ids:
            try:
                if random_photo:
                    bot.send_photo(chat_id, random_photo, caption=message)
                else:
                    bot.send_message(chat_id, message)
            except Exception as e:
                print(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
    except Exception as e:
        print(f"Ошибка при отправке утренней рассылки: {e}")

def run_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(morning_mailing, 'cron', minute='*')
    scheduler.start()
    
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

scheduler_thread = Thread(target=run_scheduler)
scheduler_thread.daemon = True
scheduler_thread.start()

def form_birth(message):
    user_id = message.from_user.id
    try:
        birth_date = datetime.strptime(message.text, config.DATE_FORMAT)
        formatted_date = birth_date.strftime(config.DATE_FORMAT)
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("UPDATE birthdays SET birthday_date = ? WHERE user_id = ?", (formatted_date, user_id))
        bot.send_message(message.chat.id, "Дата рождения успешно добавлена")
        if user_id in user_states:
            del user_states[user_id]
    except ValueError:
        error_msg = f"Неверный формат даты. Пожалуйста, используйте формат: {config.DATE_FORMAT.replace('%d', 'ДД').replace('%m', 'ММ').replace('%Y', 'ГГГГ')}"
        bot.send_message(message.chat.id, error_msg)
        msg = bot.send_message(message.chat.id, "Попробуйте еще раз:")
        bot.register_next_step_handler(msg, form_birth)
    except Exception as e:
        error_msg = f"Произошла ошибка: {str(e)}"
        bot.send_message(message.chat.id, error_msg)
        if user_id in user_states:
            del user_states[user_id] 
      
def get_photo(message):
    request = message.text
    user_id = message.from_user.id
    
    if not message.text:
        bot.send_message(message.chat.id, "Пожалуйста, введите текстовую подпись.")
        return
    
    try:
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("SELECT file_id FROM photo WHERE caption = ?", (request,))
            result = c.fetchone()
            if result:
                file_id = result[0]
                bot.send_photo(message.chat.id, file_id, caption="Вот ваше фото!")
                if user_id in user_states:
                    del user_states[user_id]
            else:
                bot.send_message(message.chat.id, "Фото по запросу не найдено. Попробуйте другую подпись или введите /cancel для отмены.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка при получении фото: {str(e)}")
        
@bot.message_handler(commands=["start"], chat_types=['private'])
def main(message):
    bot.send_message(message.chat.id, f"Привет, {message.from_user.first_name}!")
    
@bot.message_handler(commands=["add_info"], chat_types=['private'])
def add_user(message):
    user_id = message.from_user.id
    name = message.from_user.username or "Null"
    markup0 = types.InlineKeyboardMarkup()
    markup0.add(types.InlineKeyboardButton("Добавить дату рождения", callback_data="add_birthday"))

    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("INSERT OR REPLACE INTO birthdays (user_id, user) VALUES (?, ?)", (user_id, name))
    
    bot.reply_to(message, f"{message.from_user.first_name}, ваш ID и Username добавлены в базу, теперь добавьте дату рождения", reply_markup=markup0)
  
@bot.callback_query_handler(func=lambda callback: True)
def callback_message(callback):
    if callback.data == "add_birthday":
        user_states[callback.from_user.id] = "waiting_birthday"
        msg = bot.send_message(callback.message.chat.id, f"Введите дату рождения в формате {config.DATE_FORMAT.replace('%d', 'ДД').replace('%m', 'ММ').replace('%Y', 'ГГГГ')}")
        bot.register_next_step_handler(msg, form_birth)
        
@bot.message_handler(commands=["add_photo"], chat_types=['private'])
def add_photo(message):
    if message.from_user.id in admin_ids:
        user_states[message.from_user.id] = "waiting_photo"
        msg = bot.send_message(message.chat.id, "Загрузите фото и добавьте к нему подпись (необязательно)")
    else:
        bot.send_message(message.chat.id, f"{message.from_user.first_name}, у вас нет прав для загрузки изображений")
       
@bot.message_handler(commands=["get_photo"], chat_types=["private"])
def request_photo(message):
    user_id = message.from_user.id
    user_states[user_id] = "waiting_get_photo"
    bot.send_message(message.chat.id, "Напишите подпись фото для того, чтобы я вам его вывел")
            
@bot.message_handler(content_types=['photo'], chat_types=['private'])
def handle_photo(message):
    user_id = message.from_user.id
    if user_id in user_states and user_states[user_id] == "waiting_photo":
        try:
            file_id = message.photo[-1].file_id
            caption = message.caption or "Нет подписи"
            with sql.connect(config.DB_NAME) as con:
                c = con.cursor()
                c.execute("INSERT INTO photo (file_id, caption) VALUES (?, ?)", (file_id, caption))
            bot.reply_to(message, "Фото успешно сохранено!")
            del user_states[user_id]
        except Exception as e:
            bot.reply_to(message, f"Ошибка при сохранении: {str(e)}")
            if user_id in user_states:
                del user_states[user_id]
    else:
        if message.from_user.id in admin_ids:
            bot.reply_to(message, "Чтобы сохранить фото, используйте команду /add_photo")
        else:
            bot.send_message(message.chat.id, "Ошибка!")

@bot.message_handler(commands=["cancel"], chat_types=['private'])
def cancel(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        bot.send_message(message.chat.id, "Текущее действие отменено.")
    else:
        bot.send_message(message.chat.id, "Нет активных действий для отмены.")

@bot.message_handler(commands=["add_chat"], chat_types=['private'])
def add_chat_command(message):
    if message.from_user.id in admin_ids:
        try:
            if len(message.text.split()) > 1:
                chat_id = int(message.text.split()[1])
                try:
                    chat_info = bot.get_chat(chat_id)
                    title = chat_info.title
                    add_chat(chat_id, title)
                    bot.reply_to(message, f"Чат '{title}' (ID: {chat_id}) добавлен для утренней рассылки!")
                except Exception as e:
                    bot.reply_to(message, f"Не удалось добавить чат. Ошибка: {str(e)}")
            else:
                chat_id = message.chat.id
                title = message.chat.title
                add_chat(chat_id, title)
                bot.reply_to(message, f"Текущий чат: {title}, имеющий ID: {chat_id}, успешно добавлен для утренней рассылки")
        except ValueError:
            bot.reply_to(message, "Неверный формат ID чата.")
        except Exception as e:
            bot.reply_to(message, f"Произошла ошибка: {str(e)}")
    else:
        bot.reply_to(message, "Недостаточно прав")

@bot.message_handler(commands=["set_mailing_time"], chat_types=['private'])
def set_mailing_time(message):
    if message.from_user.id in admin_ids:
        try:
            parts = message.text.split()
            if len(parts) == 3:
                chat_id = int(parts[1])
                mailing_time = parts[2]
                try:
                    datetime.strptime(mailing_time, config.TIME_FORMAT)
                    update_chat_mailing_time(chat_id, mailing_time)
                    bot.reply_to(message, f"Время рассылки для чата {chat_id} установлено на {mailing_time}")
                except ValueError:
                    bot.reply_to(message, f"Неверный формат времени. Используйте {config.TIME_FORMAT.replace('%H:%M', 'ЧЧ:MM')}")
            else:
                bot.reply_to(message, "Используйте: /set_mailing_time <chat_id> <время в формате ЧЧ:MM>")
        except ValueError:
            bot.reply_to(message, "Неверный формат ID чата.")
        except Exception as e:
            bot.reply_to(message, f"Произошла ошибка: {str(e)}")
    else:
        bot.reply_to(message, "Недостаточно прав")

@bot.message_handler(commands=["get_chat_id"])
def get_chat_id(message):
    chat_id = message.chat.id
    title = message.chat.title
    bot.reply_to(message, f"Вот ID чата({title}): {chat_id}")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    if message.chat.type != 'private' and user_id not in user_states:
        return
    if user_id in user_states:
        state = user_states[user_id]
        if state == "waiting_birthday":
            form_birth(message)
        elif state == "waiting_photo":
            bot.send_message(message.chat.id, "Пожалуйста, загрузите изображение, а не текст")
        elif state == "waiting_get_photo":
            get_photo(message)
        else:
            bot.send_message(message.chat.id, "Ваше сообщение не обработано, воспользуйтесь меню команд")

bot.infinity_polling()