"""Rewraps every workspace's data key with the current ZOO_SECRETS_KEY or ZOO_KMS, and moves secrets, agent keys,
VNC passwords and app profiles from before envelope encryption onto their workspace's data key.

Set the new ZOO_SECRETS_KEY (or ZOO_KMS), put the old key in ZOO_SECRETS_KEY_PREVIOUS (and keep the old KMS's
credentials set), run `make rotate-secrets`, then drop ZOO_SECRETS_KEY_PREVIOUS.
"""

from dotenv import load_dotenv

load_dotenv()

from db.connection import db_manager
from server.sandbox_api import PROFILE_DIR
from server.security import rotate

if __name__ == "__main__":
    db_manager.init_db()
    with db_manager.session() as db:
        print(rotate(db, PROFILE_DIR))
