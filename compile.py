import PyInstaller.__main__

bot_script = "main.py"

params = [
    "--name=TelegramBirthdayBot",
    "--onefile",
    "--console",
    "--icon=NONE",
    "--add-data=config.py;.",
    "--add-data=bot.db;.",
    "--hidden-import=sqlite3",
    "--hidden-import=telebot",
    "--hidden-import=apscheduler",
    "--hidden-import=apscheduler.schedulers",
    "--hidden-import=apscheduler.schedulers.background",
    bot_script
]

PyInstaller.__main__.run(params)