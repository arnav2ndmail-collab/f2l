import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN    = os.environ["BOT_TOKEN"]
BOT_USERNAME = os.environ["BOT_USERNAME"]   # without @
RATE_LIMIT   = int(os.environ.get("RATE_LIMIT", 10))
DB_PATH      = os.environ.get("DB_PATH", "filelink.db")
