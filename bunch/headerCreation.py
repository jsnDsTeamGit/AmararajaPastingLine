import hmac
import hashlib


def hash_message_create(request_key: str, secret_key: str) -> str:
    modified_message = remove_first_and_last_three_letters(request_key)
    odd_index_characters = get_odd_index_characters(modified_message)
    request_key = odd_index_characters
    hash_bytes = hmac.new(
        secret_key.encode("utf-8"),
        request_key.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hash_bytes

def remove_first_and_last_three_letters(message: str) -> str:
    if len(message) <= 6:
        return ""
    return message[3:-3].strip()

def get_odd_index_characters(message: str) -> str:
    # odd positions (1-based index) = even indexes (0-based)
    return "".join([char for idx, char in enumerate(message) if (idx + 1) % 2 != 0])

def CreateHeader(randomKey):
    secretKey = "7a3478ef9f0e4c38a3ee1955711b2677"
    apiKey = "4444939d01fe4c2fb0edc8d784e2930c"
    hashValue = hash_message_create(randomKey, secretKey)
    header = {
        "Content-Type": "application/json",
        "X-API-Key":apiKey,
        "X-Random-Key": randomKey,
        "X-CheckSumValue-Key": hashValue,
    }
    return header