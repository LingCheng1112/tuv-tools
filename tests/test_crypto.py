"""测试 RSA 加密"""

import base64

from Crypto.PublicKey import RSA

from tuv_tools.core.chapter.crypto import derive_public_key, encrypt_password

_TEST_KEY = RSA.generate(1024)
_TEST_PRIVATE_B64 = base64.b64encode(_TEST_KEY.export_key("DER", pkcs=8)).decode()


class TestCrypto:
    def test_derive_public_key(self):
        pub_b64 = derive_public_key(_TEST_PRIVATE_B64)
        pub_der = base64.b64decode(pub_b64)
        pub_key = RSA.import_key(pub_der)
        assert pub_key.n == _TEST_KEY.n
        assert pub_key.e == _TEST_KEY.e

    def test_encrypt_password_produces_base64(self):
        encrypted = encrypt_password("123456", _TEST_PRIVATE_B64)
        raw = base64.b64decode(encrypted)
        assert len(raw) > 0

    def test_encrypt_decrypt_roundtrip(self):
        from Crypto.Cipher import PKCS1_v1_5
        password = "test_password_123"
        encrypted = encrypt_password(password, _TEST_PRIVATE_B64)
        cipher = PKCS1_v1_5.new(_TEST_KEY)
        decrypted = cipher.decrypt(base64.b64decode(encrypted), sentinel=b"FAIL")
        assert decrypted.decode() == password

    def test_encrypt_long_password(self):
        from Crypto.Cipher import PKCS1_v1_5
        long_pw = "a" * 200
        encrypted = encrypt_password(long_pw, _TEST_PRIVATE_B64)
        cipher = PKCS1_v1_5.new(_TEST_KEY)
        raw = base64.b64decode(encrypted)
        key_size = 128
        blocks = [raw[i:i+key_size] for i in range(0, len(raw), key_size)]
        decrypted = b""
        for block in blocks:
            decrypted += cipher.decrypt(block, sentinel=b"FAIL")
        assert decrypted.decode() == long_pw
