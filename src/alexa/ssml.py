from __future__ import annotations


class Ssml:
    @staticmethod
    def ssml(text: str, pause_ms: int = 400) -> str:
        return f'<speak><break time="{pause_ms}ms"/>{text}</speak>'
