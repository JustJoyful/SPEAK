import unittest
import os
from backend.pipeline.crypto import encrypt_payload, decrypt_payload
from backend.pipeline.hash_chain import compute_record_hash, verify_record_hash

class TestCryptoHash(unittest.TestCase):
    def setUp(self):
        os.environ["AES_ENCRYPTION_KEY"] = "TUVEU1lOQ19ERUZBVUxUX1NFQ1VSRV9LRVlfMzJCXyE="
        os.environ["ABDM_SALT"] = "test-salt"

    def test_aes_gcm_round_trip(self):
        payload = '{"resource_type": "Bundle", "type": "document"}'
        
        # Encrypt
        encrypted = encrypt_payload(payload)
        
        self.assertIn("payload", encrypted)
        self.assertIn("nonce", encrypted)
        self.assertIn("tag", encrypted)
        
        # Decrypt
        decrypted = decrypt_payload(
            encrypted["payload"],
            encrypted["nonce"],
            encrypted["tag"]
        )
        
        self.assertEqual(decrypted, payload)

    def test_aes_gcm_tamper_detection(self):
        payload = '{"resource_type": "Bundle", "type": "document"}'
        encrypted = encrypt_payload(payload)
        
        # Tamper with the ciphertext (payload)
        tampered_payload = encrypted["payload"][:-1] + ('A' if encrypted["payload"][-1] != 'A' else 'B')
        
        with self.assertRaisesRegex(ValueError, "Decryption failed: Data tampering detected or invalid key."):
            decrypt_payload(tampered_payload, encrypted["nonce"], encrypted["tag"])

    def test_hash_chain_integrity(self):
        plaintext = '{"resource_type": "Bundle", "type": "document"}'
        genesis_hash = "0" * 64
        
        record_hash = compute_record_hash(plaintext, genesis_hash)
        
        self.assertEqual(len(record_hash), 64)
        self.assertTrue(verify_record_hash(plaintext, genesis_hash, record_hash))
        
        # Verify failure on tampered content
        tampered_plaintext = '{"resource_type": "Bundle", "type": "transaction"}'
        self.assertFalse(verify_record_hash(tampered_plaintext, genesis_hash, record_hash))
        
        # Verify failure on tampered previous hash
        tampered_genesis = genesis_hash[:-1] + "1"
        self.assertFalse(verify_record_hash(plaintext, tampered_genesis, record_hash))

if __name__ == '__main__':
    unittest.main()
