import base64
import hashlib
import traceback
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Custom keys
CUSTOM_SALT_KEY = "8JTJdeP9aO_%0+,"
CUSTOM_IV_KEY = "~OdzY4.S@;Iw&1L"

def generate_custom_key():
    """Generate a 256-bit key from the custom salt."""
    return hashlib.sha256(CUSTOM_SALT_KEY.encode()).digest()

def generate_custom_iv():
    """Generate a 12-byte IV from the custom IV key."""
    iv = CUSTOM_IV_KEY.encode()
    return iv[:12].ljust(12, b'\x00')  # Ensure it's exactly 12 bytes

def encrypt(plain_text: str) -> str:
    """Encrypts the plain text using AES-GCM."""
    key = generate_custom_key()
    iv = generate_custom_iv()
    aesgcm = AESGCM(key)
    
    plain_text_bytes = plain_text.encode()
    cipher_text = aesgcm.encrypt(iv, plain_text_bytes, None)
    return base64.b64encode(cipher_text).decode()

def decrypt(encrypted_text: str) -> str:
    """Decrypts the encrypted text using AES-GCM."""
    try:
        key = generate_custom_key()
        iv = generate_custom_iv()
        aesgcm = AESGCM(key)
        encrypted_data = base64.b64decode(encrypted_text)
        decrypted_bytes = aesgcm.decrypt(iv, encrypted_data, None)
        return True, decrypted_bytes.decode()
    except Exception as e:
        return False, str(traceback.format_exc())
