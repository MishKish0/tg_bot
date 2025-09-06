import sqlite3

conn = sqlite3.connect('bot.db')
cursor = conn.cursor()
cursor.execute("UPDATE birthdays SET chat_id = ? WHERE chat_id IS NULL", (YOUR_CHAT_ID,))
conn.commit()
conn.close()

print("Записи успешно обновлены!")