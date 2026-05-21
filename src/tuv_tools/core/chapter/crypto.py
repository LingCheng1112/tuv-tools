"""RSA 密码加密（兼容后端 Java RsaUtils）"""

from __future__ import annotations

import base64

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


def derive_public_key(private_key_b64: str) -> str:
    """从 Base64 PKCS8 私钥推导公钥（DER 格式 Base64）"""
    private_der = base64.b64decode(private_key_b64)
    private_key = RSA.import_key(private_der)
    public_der = private_key.publickey().export_key("DER")
    return base64.b64encode(public_der).decode()


def encrypt_password(password: str, private_key_b64: str) -> str:
    """用 RSA 公钥分块加密密码，输出 Base64 密文"""
    pub_b64 = derive_public_key(private_key_b64)
    pub_der = base64.b64decode(pub_b64)
    pub_key = RSA.import_key(pub_der)
    cipher = PKCS1_v1_5.new(pub_key)

    data = password.encode("utf-8")
    key_size = pub_key.size_in_bytes()  # 128 for 1024-bit
    max_block = key_size - 11  # PKCS1 padding overhead

    encrypted = b""
    for i in range(0, len(data), max_block):
        block = data[i:i + max_block]
        encrypted += cipher.encrypt(block)

    return base64.b64encode(encrypted).decode()
