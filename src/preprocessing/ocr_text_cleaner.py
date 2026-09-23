import re
import unicodedata


class OCRTextCleaner:

    def clean(self, text: str) -> str:

        if not text:
            return ""

        text = self._normalize_unicode(text)
        text = self._normalize_whitespace(text)
        text = self._fix_line_breaks(text)
        text = self._remove_noise(text)

        return text.strip()

    @staticmethod
    def _normalize_unicode(text: str) -> str:
        return unicodedata.normalize("NFKC", text)

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")

        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text

    @staticmethod
    def _fix_line_breaks(text: str) -> str:
        lines = [
            line.strip()
            for line in text.split("\n")
        ]

        return "\n".join(
            line for line in lines if line
        )

    @staticmethod
    def _remove_noise(text: str) -> str:
        return re.sub(
            r"[^\S\n]+",
            " ",
            text
        )