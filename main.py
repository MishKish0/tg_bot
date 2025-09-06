import sqlite3 as sql
from datetime import datetime
from threading import Thread
import time
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import config

bot = telebot.TeleBot(config.BOT_TOKEN)
admin_ids = config.ADMIN_IDS
user_states = {}

def init_db():
    with sql.connect(config.DB_NAME) as con:
        c = con.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS birthdays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            birthday_date TEXT NOT NULL,
            chat_id INTEGER,
            FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
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

def get_random_cat():
    try:
        response = requests.get('https://api.thecatapi.com/v1/images/search')
        if response.status_code == 200:
            return response.json()[0]['url']
        else:
            return None
    except Exception as e:
        print(f"Ошибка при загрузке котика: {e}")
        return None

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
        today = datetime.now().strftime("%d-%m")
        random_photo = get_random_photo()
        if not random_photo:
            random_photo = get_random_cat()
        
        chat_ids = get_chats_for_mailing()
        
        if not chat_ids:
            return
            
        for chat_id in chat_ids:
            try:
                with sql.connect(config.DB_NAME) as con:
                    c = con.cursor()
                    c.execute("SELECT name FROM birthdays WHERE substr(birthday_date, 1, 5) = ? AND chat_id = ?", (today, chat_id))
                    birthdays = [row[0] for row in c.fetchall()]
                
                if birthdays:
                    if len(birthdays) == 1:
                        message = f"Сегодня {birthdays[0]} празднует день рождения! 😺🎉\nПоздравляем!"
                    elif len(birthdays) == 2:
                        message = f"Сегодня {birthdays[0]} и {birthdays[1]} празднуют день рождения! 😺🎉\nПоздравляем!🥳"
                    else:
                        message = "Сегодня дни рождения у:\n"
                        for name in birthdays:
                            message += f"🎂 {name}\n"
                        message += "Поздравляем всех именинников!😺🎉"
                else:
                    message = "Доброе утро!😺"
                
                if random_photo:
                    if isinstance(random_photo, str) and random_photo.startswith('http'):
                        bot.send_photo(chat_id, random_photo, caption=message)
                    else:
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
    
@bot.message_handler(commands=["add_photo"], chat_types=['private'])
def add_photo_command(message):
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
        bot.send_message(message.chat.id, "Текущее действия отменено.")
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
                    bot.reply_to(message, f"Неверный формат времени. Используйте {config.TIME_FORMAT}")
            else:
                bot.reply_to(message, f"Используйте: /set_mailing_time <chat_id> <время в формате {config.TIME_FORMAT}>")
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

@bot.message_handler(content_types=['new_chat_members'], chat_types=['group', 'supergroup'])
def handle_new_members(message):
    for new_member in message.new_chat_members:
        if new_member.id == bot.get_me().id:
            welcome_text = (
                "Привет! Я бот для утренних рассылок и поздравлений с днем рождения.\n\n"
                "Администраторы бота могут настроить время рассылки с помощью /set_mailing_time"
            )
            bot.send_message(message.chat.id, welcome_text)

@bot.message_handler(commands=["add_birthday"], chat_types=['group', 'supergroup', 'private'])
def add_birthday_command(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Недостаточно прав")
        return
        
    try:
        if message.chat.type in ['group', 'supergroup']:
            chat_id = message.chat.id
            parts = message.text.split(maxsplit=2)
            if len(parts) < 3:
                bot.reply_to(message, f"Используйте: /add_birthday {config.DATE_FORMAT.replace('%', '')} Имя Фамилия")
                return
            date_str = parts[1]
            name = parts[2]
        else:
            parts = message.text.split(maxsplit=3)
            if len(parts) < 4:
                bot.reply_to(message, f"Используйте: /add_birthday chat_id {config.DATE_FORMAT.replace('%', '')} Имя Фамилия")
                return
            try:
                chat_id = int(parts[1])
            except ValueError:
                bot.reply_to(message, "Неверный формат chat_id. Используйте целое число.")
                return
            date_str = parts[2]
            name = parts[3]
        
        try:
            birth_date = datetime.strptime(date_str, config.DATE_FORMAT)
            formatted_date = birth_date.strftime(config.DATE_FORMAT)
        except ValueError:
            bot.reply_to(message, f"Неверный формат даты. Используйте: {config.DATE_FORMAT.replace('%', '')}")
            return
            
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("SELECT 1 FROM chats WHERE chat_id = ?", (chat_id,))
            if not c.fetchone():
                bot.reply_to(message, f"Чат с ID {chat_id} не найден в базе. Сначала добавьте чат с помощью /add_chat")
                return
            
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("INSERT INTO birthdays (name, birthday_date, chat_id) VALUES (?, ?, ?)",
                     (name, formatted_date, chat_id))
                     
        bot.reply_to(message, f"День рождения для {name} установлен на {formatted_date} в чате {chat_id}")
            
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка: {str(e)}")

@bot.message_handler(commands=["remove_birthday"], chat_types=['private'])
def remove_birthday_command(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Недостаточно прав")
        return  
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "Используйте: /remove_birthday chat_id Имя Фамилия")
            return
        try:
            chat_id = int(parts[1])
        except ValueError:
            bot.reply_to(message, "Неверный формат chat_id. Используйте целое число.")
            return
        name = parts[2]
        
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("DELETE FROM birthdays WHERE name = ? AND chat_id = ?", (name, chat_id))
            
            if c.rowcount > 0:
                bot.reply_to(message, f"День рождения для {name} в чате {chat_id} удален")
            else:
                bot.reply_to(message, f"День рождения для {name} в чате {chat_id} не найден")
            
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка: {str(e)}")

@bot.message_handler(commands=["list_birthdays"], chat_types=['private'])
def list_birthdays_command(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Недостаточно прав")
        return
        
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Используйте: /list_birthdays chat_id")
            return
        try:
            chat_id = int(parts[1])
        except ValueError:
            bot.reply_to(message, "Неверный формат chat_id. Используйте целое число.")
            return
        
        with sql.connect(config.DB_NAME) as con:
            c = con.cursor()
            c.execute("SELECT name, birthday_date FROM birthdays WHERE chat_id = ? ORDER BY birthday_date", (chat_id,))
            birthdays = c.fetchall()
            
            if not birthdays:
                bot.reply_to(message, f"В чате {chat_id} нет дней рождения")
                return
                
            message_text = f"Список дней рождения в чате {chat_id}:\n\n"
            for name, date in birthdays:
                message_text += f"{name} - {date}\n"
                
            bot.reply_to(message, message_text)
            
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    if message.chat.type != 'private' and user_id not in user_states:
        return
    if user_id in user_states:
        state = user_states[user_id]
        if state == "waiting_photo":
            bot.send_message(message.chat.id, "Пожалуйста, загрузите изображение, а не текст")
        elif state == "waiting_get_photo":
            get_photo(message)
        else:
            bot.send_message(message.chat.id, "Ваше сообщение не обработано, воспользуйтесь меню команд")

bot.infinity_polling()