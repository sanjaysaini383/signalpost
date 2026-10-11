"""Norwegian organisation number validation (9 digits, mod-11 check digit)."""
import re

_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def normalize(value: str) -> str:
    return re.sub(r"[\s.]", "", str(value))


def is_valid(value: str) -> bool:
    org = normalize(value)
    if not re.fullmatch(r"\d{9}", org):
        return False
    total = sum(int(d) * w for d, w in zip(org[:8], _WEIGHTS))
    check = 11 - total % 11
    if check == 11:
        check = 0
    return check != 10 and check == int(org[8])
