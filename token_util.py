import jwt
from jwt.exceptions import InvalidTokenError
from functools import wraps
from flask import request, jsonify, render_template, redirect
import time,redis  

# 定义token验证装饰器
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs)
        try:
            token = request.headers.get('token')
            if not token:
                return jsonify({"status": "error", "message": "token is required"}), 401

            # 验证 JWT 签名并获取 userId
            user_id = verify_token(token)
            if not user_id:
                return jsonify({"status": "error", "message": "invalid token payload"}), 401

            # 生成 Java 序列化格式的 key（bytes）
            key = java_serialize_string(token)

            # 检查该 key 是否存在于 Redis
            if not redis_client.exists(key):
                return jsonify({"status": "error", "message": "token is expired or revoked"}), 401

        except Exception as e:
            print("Token validation error:", str(e))
            return jsonify({"status": "error", "message": "authentication failed"}), 401

        return f(*args, **kwargs)
    return decorated

def verify_token(token: str) -> str:
    try:
        # 使用 HMAC256 算法和密钥 "secret" 验证 Token
        payload = jwt.decode(
            token,
            key="secret",
            algorithms=["HS256"],
            options={"verify_signature": True}
        )
        # 返回 userId
        return payload.get("userId")
    except jwt.exceptions.InvalidTokenError as e:
        raise InvalidTokenError("Token 验证失败") from e
    
    
# 初始化 Redis 连接
redis_client1 = redis.Redis(
    host='172.16.33.129',  # Redis 服务器地址
    port=6379,        # Redis 端口
    db=0,             # 数据库索引
    password='QEh$T2TJlQaCmGkm',   # Redis 密码
    decode_responses=False  # 自动解码返回值为字符串
)
# 初始化 Redis 连接
redis_client = redis.Redis(
    host='10.30.253.13',  # Redis 服务器地址
    port=6379,        # Redis 端口
    db=0,             # 数据库索引
    password='0hx65STUjBxiiirgzx',   # Redis 密码
    decode_responses=False  # 自动解码返回值为字符串
)

def java_serialize_string(s: str) -> bytes:
    utf8 = s.encode('utf-8')
    length = len(utf8)
    if length > 65535:
        raise ValueError("String too long")
    return b'\xac\xed\x00\x05t' + length.to_bytes(2, 'big') + utf8
