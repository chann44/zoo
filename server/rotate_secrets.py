"""Re-encrypts every secret, agent key and app profile with the current ZOO_SECRETS_KEY.

Set the new ZOO_SECRETS_KEY, put the old one in ZOO_SECRETS_KEY_PREVIOUS, run `make rotate-secrets`,
then drop ZOO_SECRETS_KEY_PREVIOUS.
"""

import os

from dotenv import load_dotenv

load_dotenv()

from db.connection import db_manager
from server.sandbox_api import PROFILE_DIR
from server.security import rotate

if __name__ == "__main__":
    db_manager.init_db(os.environ.get("DB_PATH", "./local.db"))
    with db_manager.session() as db:
        print(rotate(db, PROFILE_DIR))
