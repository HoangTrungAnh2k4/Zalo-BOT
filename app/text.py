"""Tiện ích xử lý chuỗi tiếng Việt."""
import unicodedata

# So khớp có dấu: "minh" (không dấu) vẫn có thể là tên của người tên Minh.
SELF_ALIASES = frozenset({"tôi", "toi", "mình", "tui", "tao"})
# So khớp sau khi đã chuẩn hóa (không dấu, chữ thường).
EVERYONE_PHRASES = frozenset({"tat ca", "moi nguoi", "ca nhom", "het", "all"})


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt: "Hòa Đức" -> "Hoa Duc"."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize(text: str) -> str:
    """Chuẩn hóa để so khớp: bỏ dấu, chữ thường, gộp khoảng trắng."""
    return " ".join(strip_accents(text).lower().split())


def clean(text: str, max_length: int) -> str:
    """Gộp khoảng trắng và cắt độ dài, giữ nguyên dấu để hiển thị."""
    return " ".join(nfc(text).split())[:max_length].strip()
