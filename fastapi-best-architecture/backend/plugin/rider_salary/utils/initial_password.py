import secrets

_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_DIGITS = '23456789'
_SPECIAL = '!@#$%'
_LENGTH = 12


def generate_initial_password() -> str:
    """生成只在当次响应返回的随机初始密码，含字母、数字和特殊字符。"""
    chars = [
        secrets.choice(_LETTERS),
        secrets.choice(_DIGITS),
        secrets.choice(_SPECIAL),
    ]
    alphabet = _LETTERS + _DIGITS + _SPECIAL
    chars.extend(secrets.choice(alphabet) for _ in range(_LENGTH - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)
