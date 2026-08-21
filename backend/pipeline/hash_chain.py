import hashlib

def compute_record_hash(plaintext_payload: str, prev_hash: str) -> str:
    """
    Computes a SHA-256 blockchain-style ledger hash for the record.
    Combines the plaintext content with the previous block's hash to form a tamper-evident chain.
    """
    hasher = hashlib.sha256()
    hasher.update(plaintext_payload.encode('utf-8'))
    hasher.update(prev_hash.encode('utf-8'))
    return hasher.hexdigest()

def verify_record_hash(plaintext_payload: str, prev_hash: str, expected_hash: str) -> bool:
    """
    Verifies that the given plaintext and prev_hash produce the expected_hash.
    """
    return compute_record_hash(plaintext_payload, prev_hash) == expected_hash
