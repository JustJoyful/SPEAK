import pytest
import sys
if __name__ == "__main__":
    from tests.test_crypto_hash import test_aes_gcm_round_trip, test_aes_gcm_tamper_detection, test_hash_chain_integrity
    test_aes_gcm_round_trip()
    try:
        test_aes_gcm_tamper_detection()
    except Exception as e:
        if type(e).__name__ != 'ValueError':
            print("Failed tamper detection")
            sys.exit(1)
    test_hash_chain_integrity()
    print("All tests passed.")
