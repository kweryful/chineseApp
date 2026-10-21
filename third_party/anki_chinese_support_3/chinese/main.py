"""Standalone host bridge for the Chinese Support 3 modules."""

from .database import Dictionary

config = {
    "fields": {
        "hanzi": ["Chinese", "Expression", "Hanzi", "中文", "汉字", "漢字"],
    }
}
dictionary = Dictionary()
