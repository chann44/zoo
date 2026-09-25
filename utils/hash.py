import bcrypt

def hash_pass(orignal: str) -> str:
    bytes = orignal.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(bytes, salt=salt)
    return hashed_bytes.decode("utf-8")

def verify_pass(hashed: str, orignal: str) -> str:
    hashed_btyes = hashed.encode("utf-8")
    orignal_btyes = orignal.encode("utf-8")
    return bcrypt.checkpw(orignal_btyes,hashed_password=hashed_btyes)
    