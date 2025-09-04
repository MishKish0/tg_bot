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
        birthday_date TEXT
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
        
        c.execute("""CREATE TABLE IF NOT EXISTS user_chats (
            user_id INTEGER,
            chat_id INTEGER,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            PRIMARY KEY (user_id, chat_id)
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

def update_user_chat_info(chat_id, user_id, username, first_name, last_name):
    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("""INSERT OR REPLACE INTO user_chats 
                    (user_id, chat_id, username, first_name, last_name) 
                    VALUES (?, ?, ?, ?, ?)""",
                 (user_id, chat_id, username, first_name, last_name))

def update_chat_members():
    try:
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("SELECT chat_id FROM chats WHERE is_active = 1")
            active_chats = [row[0] for row in c.fetchall()]
            
            for chat_id in active_chats:
                try:
                    admins = bot.get_chat_administrators(chat_id)
                    
                    for admin in admins:
                        user = admin.user
                        update_user_chat_info(chat_id, user.id, user.username, user.first_name, user.last_name)
                        
                    print(f"Обновлена информация об администраторах чата {chat_id}")
                except Exception as e:
                    print(f"Ошибка при обновлении участников чата {chat_id}: {e}")
    except Exception as e:
        print(f"Ошибка при обновлении списка участников: {e}")

def morning_mailing():
    try:
        today = datetime.now().strftime("%d-%m")
        random_photo = get_random_photo()
        chat_ids = get_chats_for_mailing()
        
        if not chat_ids:
            return
            
        for chat_id in chat_ids:
            try:
                with sql.connect(config.DB_NAME) as con:
                    c = con.cursor()
                    c.execute("""SELECT DISTINCT b.user 
                                FROM birthdays b
                                JOIN user_chats uc ON b.user_id = uc.user_id
                                WHERE substr(b.birthday_date, 1, 5) = ?
                                AND uc.chat_id = ?""", (today, chat_id))
                    birthdays = [row[0] for row in c.fetchall()]
                
                if birthdays:
                    message = "Сегодня день рождения у:\n"
                    for user in birthdays:
                        message += f"@{user}\n"
                    message += "Поздравляем!"
                else:
                    message = "Доброе утро!"
                
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
    scheduler.add_job(update_chat_members, 'cron', hour=3)
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
    
@bot.message_handler(commands=["set_birthday"], chat_types=['private'])
def set_birthday(message):
    user_id = message.from_user.id
    name = message.from_user.username or "Null"
    
    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("INSERT OR REPLACE INTO birthdays (user_id, user) VALUES (?, ?)", (user_id, name))
    
    user_states[user_id] = "waiting_birthday"
    msg = bot.send_message(message.chat.id, f"Введите дату рождения в формате {config.DATE_FORMAT.replace('%d', 'ДД').replace('%m', 'ММ').replace('%Y', 'ГГГГ')}")
    bot.register_next_step_handler(msg, form_birth)
  
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

@bot.message_handler(commands=["update_members"], chat_types=['group', 'supergroup'])
def update_members_command(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Эта команда доступна только администраторам бота.")
        return
        
    chat_id = message.chat.id
    try:
        admins = bot.get_chat_administrators(chat_id)
        for admin in admins:
            user = admin.user
            update_user_chat_info(chat_id, user.id, user.username, user.first_name, user.last_name)
        
        bot.reply_to(message, f"Информация об администраторах чата обновлена. Добавлено/обновлено {len(admins)} записей.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при обновлении информации: {str(e)}")

@bot.message_handler(commands=["get_chat_id"])
def get_chat_id(message):
    chat_id = message.chat.id
    title = message.chat.title
    bot.reply_to(message, f"Вот ID чата({title}): {chat_id}")

@bot.message_handler(content_types=['text'], chat_types=['group', 'supergroup'])
def handle_group_messages(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    chat_id = message.chat.id
    
    update_user_chat_info(chat_id, user_id, username, first_name, last_name)

@bot.message_handler(content_types=['new_chat_members'], chat_types=['group', 'supergroup'])
def handle_new_members(message):
    for new_member in message.new_chat_members:
        if not new_member.is_bot:
            user_id = new_member.id
            username = new_member.username
            first_name = new_member.first_name
            last_name = new_member.last_name
            chat_id = message.chat.id
            
            update_user_chat_info(chat_id, user_id, username, first_name, last_name)
            
            if new_member.id == bot.get_me().id:
                welcome_text = (
                    "Привет! Я бот для утренних рассылок и поздравлений с днем рождения.\n\n"
                    "Чтобы я мог вас поздравить, пожалуйста:\n"
                    "1. Напишите любое сообщение в этот чат\n"
                    "2. Установите свою дату рождения с помощью команды /set_birthday в личных сообщениях со мной\n\n"
                    "Администраторы могут настроить время рассылки с помощью /set_mailing_time"
                )
                bot.send_message(message.chat.id, welcome_text)

@bot.message_handler(commands=["admin_add_birthday"], chat_types=['private'])
def admin_add_birthday(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Недостаточно прав")
        return
        
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "Используйте: /admin_add_birthday @username DD.MM.YYYY")
            return
            
        username = parts[1].replace('@', '')
        birth_date_str = parts[2]
        
        try:
            birth_date = datetime.strptime(birth_date_str, config.DATE_FORMAT)
            formatted_date = birth_date.strftime(config.DATE_FORMAT)
        except ValueError:
            bot.reply_to(message, f"Неверный формат даты. Используйте: {config.DATE_FORMAT}")
            return
            
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("SELECT user_id FROM user_chats WHERE username = ? LIMIT 1", (username,))
            result = c.fetchone()
            
            if not result:
                bot.reply_to(message, f"Пользователь @{username} не найден в базе. Он должен хотя бы раз написать в чате, где есть бот.")
                return
                
            user_id = result[0]
            
            c.execute("INSERT OR REPLACE INTO birthdays (user_id, user, birthday_date) VALUES (?, ?, ?)",
                     (user_id, username, formatted_date))
                     
            bot.reply_to(message, f"День рождения для @{username} установлен на {formatted_date}")
            
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка: {str(e)}")

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