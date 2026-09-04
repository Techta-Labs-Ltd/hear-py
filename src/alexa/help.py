from __future__ import annotations

from src.alexa.playback_speech import PlaybackSpeech


class HelpSpeech:
    GUIDE_OPENING = (
        "Here is your guide to Hear Service. To find something, say what's new, what's trending, "
        "play the latest news, play sport, or play something about a topic. You can ask for "
        "local content, a publication, a named creator, or a talking newspaper. When I read "
        "out choices, say the name or number, show more, previous choices, or none of these. "
    )
    GUIDE_CLOSING = (
        "To learn more, ask what's this about or who made this. You can "
        "follow or unfollow the creator, play content from creators you follow, rate the "
        "recording, or report inappropriate content. You can ask to hear your updates, or turn "
        "notifications on or off. To personalise Hear, say change my location or set up my "
        "account. For example, try saying, play the latest local news. What would you like to do?"
    )
    REPROMPT = (
        "Try saying what's trending, play local content, play from a talking newspaper, "
        "or play the latest news."
    )
    CARD_TITLE = "Hear - complete voice guide"
    CARD_OPENING = (
        "FIND AND BROWSE\n"
        "- What's new?\n- What's trending?\n- Play the latest news.\n- Play sport.\n"
        "- Play something about [topic].\n- Play local content / Play near [place].\n"
        "- Play a publication.\n- Play from [creator or organisation].\n"
        "- Play from a talking newspaper.\n\n"
        "CHOOSE RESULTS\n"
        "- Say a name or number: first, second, third.\n"
        "- Show more / Previous choices / None of these.\n\n"
    )
    CARD_CLOSING = (
        "LEARN AND PERSONALISE\n"
        "- What's this about? / Who made this?\n"
        "- Follow this creator / Unfollow this creator.\n"
        "- Play from my followed creators.\n"
        "- Rate this recording, then say enjoyed, it was okay, not enjoyed, or skip.\n"
        "- Report this content / Report this creator.\n- Hear my updates.\n"
        "- Turn notifications on / Turn notifications off.\n"
        "- Change my location to [place].\n- Set up my account.\n- Cancel."
    )

    @staticmethod
    def guide(stage: str) -> str:
        return f"{HelpSpeech.GUIDE_OPENING}{PlaybackSpeech.guide(stage)} {HelpSpeech.GUIDE_CLOSING}"

    @staticmethod
    def card_text(stage: str) -> str:
        return (
            f"{HelpSpeech.CARD_OPENING}{PlaybackSpeech.card_section(stage)}\n\n"
            f"{HelpSpeech.CARD_CLOSING}"
        )
