import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

# 32 bytes (256-bit) default key for demonstration if env is missing
DEFAULT_KEY = b'MEDSYNC_DEFAULT_SECURE_KEY_32B_!'

def get_encryption_key() -> bytes:
    """
    Retrieve the 256-bit AES-GCM key from the environment.
    Falls back to a default key for demonstration purposes.
    """
    key_b64 = os.getenv("AES_ENCRYPTION_KEY")
    if key_b64:
        key = base64.b64decode(key_b64)
        if len(key) != 32:
            raise ValueError("AES_ENCRYPTION_KEY must be exactly 32 bytes (256-bit) when decoded.")
        return key
    return DEFAULT_KEY

def encrypt_payload(payload: str) -> dict:
    """
    Encrypts the string payload using AES-256-GCM.
    Returns a dictionary containing the base64 encoded ciphertext (payload), nonce, and tag.
    """
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    
    # 96-bit nonce (standard for AES-GCM)
    nonce = os.urandom(12)
    payload_bytes = payload.encode('utf-8')
    
    # AESGCM.encrypt returns ciphertext with the 16-byte authentication tag appended
    encrypted_data = aesgcm.encrypt(nonce, payload_bytes, associated_data=None)
    
    # The authentication tag is the last 16 bytes (128-bit)
    ciphertext = encrypted_data[:-16]
    tag = encrypted_data[-16:]
    
    return {
        "payload": base64.b64encode(ciphertext).decode('ascii'),
        "nonce": base64.b64encode(nonce).decode('ascii'),
        "tag": base64.b64encode(tag).decode('ascii')
    }

def decrypt_payload(ciphertext_b64: str, nonce_b64: str, tag_b64: str) -> str:
    """
    Decrypts the AES-256-GCM payload using the given nonce and tag.
    Raises ValueError if data tampering is detected or the key is invalid.
    """
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    
    ciphertext = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)
    tag = base64.b64decode(tag_b64)
    
    # AESGCM.decrypt expects the ciphertext with the tag appended
    encrypted_data = ciphertext + tag
    
    try:
        decrypted_bytes = aesgcm.decrypt(nonce, encrypted_data, associated_data=None)
        return decrypted_bytes.decode('utf-8')
    except InvalidTag:
        raise ValueError("Decryption failed: Data tampering detected or invalid key.")
