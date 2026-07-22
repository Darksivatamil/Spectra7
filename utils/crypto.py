from cryptography.fernet import Fernet
import os

def get_fernet():
    key = os.getenv("FERNET_KEY")
    if not key:
        raise ValueError("FERNET_KEY not set in .env")
    return Fernet(key.encode())

def encrypt_api_key(plain_key: str) -> str:
    f = get_fernet()
    return f.encrypt(plain_key.encode()).decode()

def decrypt_api_key(encrypted_key: str) -> str:
    f = get_fernet()
    return f.decrypt(encrypted_key.encode()).decode()

def get_nvidia_key() -> str:
    encrypted = os.getenv("ENCRYPTED_NVIDIA_KEY")
    if not encrypted:
        raise ValueError("ENCRYPTED_NVIDIA_KEY not set in .env")
    return decrypt_api_key(encrypted)
