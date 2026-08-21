import os
import base64
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from backend.pipeline.fhir_schema import FHIROPConsultRecord, EncryptedBundle, SyncPointer

def get_encryption_key() -> bytes:
    """
    Retrieve the 256-bit AES-GCM key from the environment.
    """
    key_b64 = os.getenv("AES_ENCRYPTION_KEY")
    if not key_b64:
        raise ValueError("AES_ENCRYPTION_KEY environment variable is required for zero-trust encryption.")
        
    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise ValueError("AES_ENCRYPTION_KEY must be exactly 32 bytes (256-bit) when decoded.")
    return key

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

def encrypt_fhir_bundle(fhir_bundle: FHIROPConsultRecord, abha_hash: str, clinic_id: str) -> Tuple[EncryptedBundle, SyncPointer]:
    """
    Takes a plaintext FHIR R4 OP Consult bundle, computes its SHA-256 hash for the ledger,
    encrypts the payload using AES-256-GCM, and generates the Zero-Knowledge Sync Pointer.
    """
    plaintext_json = fhir_bundle.model_dump_json()
    record_hash = hashlib.sha256(plaintext_json.encode('utf-8')).hexdigest()
    
    encrypted_data = encrypt_payload(plaintext_json)
    
    bundle_id = str(uuid.uuid4())
    sync_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # Normally we'd get the prev_hash from the local DB to maintain the hash chain.
    # For now, we mock it.
    prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    
    # Extract care_context_id from the reference e.g., "CareContext/CC-12345"
    cc_ref = fhir_bundle.subject.reference
    care_context_id = cc_ref.split("/")[-1] if "/" in cc_ref else cc_ref

    encrypted_bundle = EncryptedBundle(
        bundle_id=bundle_id,
        care_context_id=care_context_id,
        payload=encrypted_data["payload"],
        nonce=encrypted_data["nonce"],
        tag=encrypted_data["tag"],
        record_hash=record_hash,
        prev_hash=prev_hash,
        created_at=now
    )
    
    sync_pointer = SyncPointer(
        sync_id=sync_id,
        abha_hash=abha_hash,
        clinic_id=clinic_id,
        record_hash=record_hash,
        timestamp=now
    )
    
    return encrypted_bundle, sync_pointer
