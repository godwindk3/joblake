"""Conservative province/city labels; preserve historical names, not boundary mapping."""
import re
import unicodedata
from collections.abc import Iterable


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", value).strip()


# Includes names still present in historical raw HTML. No automatic mergers.
_NAMES = """Hà Nội|Hồ Chí Minh|Đà Nẵng|Hải Phòng|Cần Thơ|Huế|An Giang|
Bà Rịa - Vũng Tàu|Bắc Giang|Bắc Kạn|Bạc Liêu|Bắc Ninh|Bến Tre|Bình Định|
Bình Dương|Bình Phước|Bình Thuận|Cà Mau|Cao Bằng|Đắk Lắk|Đắk Nông|Điện Biên|
Đồng Nai|Đồng Tháp|Gia Lai|Hà Giang|Hà Nam|Hà Tĩnh|Hải Dương|Hậu Giang|
Hòa Bình|Hưng Yên|Khánh Hòa|Kiên Giang|Kon Tum|Lai Châu|Lâm Đồng|Lạng Sơn|
Lào Cai|Long An|Nam Định|Nghệ An|Ninh Bình|Ninh Thuận|Phú Thọ|Phú Yên|
Quảng Bình|Quảng Nam|Quảng Ngãi|Quảng Ninh|Quảng Trị|Sóc Trăng|Sơn La|
Tây Ninh|Thái Bình|Thái Nguyên|Thanh Hóa|Thừa Thiên Huế|Tiền Giang|Trà Vinh|
Tuyên Quang|Vĩnh Long|Vĩnh Phúc|Yên Bái"""
_ALIASES = {_key(name.strip()): name.strip() for name in _NAMES.split("|")}
_ALIASES.update({
    "hanoi": "Hà Nội", "hcm": "Hồ Chí Minh", "hcmc": "Hồ Chí Minh",
    "tp hcm": "Hồ Chí Minh", "tphcm": "Hồ Chí Minh",
    "saigon": "Hồ Chí Minh", "sai gon": "Hồ Chí Minh",
    "danang": "Đà Nẵng", "haiphong": "Hải Phòng", "cantho": "Cần Thơ",
})


def location_cities(locations: Iterable[str]) -> tuple[str, ...]:
    """Match whole address components, never a city name inside a street name."""
    result: list[str] = []
    for address in locations:
        # Preserve internal hyphens in province names such as Bà Rịa - Vũng Tàu.
        for part in re.split(r"[,;:\n/|]", address):
            key = _key(part)
            key = re.sub(r"^(?:thanh pho|tinh|tp)\s+", "", key)
            key = re.sub(r"\s+(?:city|province)$", "", key)
            city = _ALIASES.get(key)
            if city and city not in result:
                result.append(city)
    return tuple(result)
