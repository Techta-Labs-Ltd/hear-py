from __future__ import annotations

from src.alexa.playback_speech import PlaybackSpeech


class HelpSpeech:
    GUIDE_OPENING = (
        "Here is your guide to Hear Service. To find something, you can simply say sport, "
        "local news, a place such as Swindon, or a talking newspaper such as Talking News Federation. "
        "You can also say what's new, what's trending, or play the latest news. When I read "
        "out choices, say the name or number, show more, previous choices, or none of these. "
    )
    GUIDE_CLOSING = (
        "To learn more, ask what's this about or who made this. You can "
        "follow or unfollow the creator, play content from creators you follow, rate the "
        "recording, or report inappropriate content. You can ask to hear your updates, or turn "
        "notifications on or off. To personalise Hear, say change my location or set up my "
        "account. For example, try saying, local news. What would you like to do?"
    )
    REPROMPT = (
        "Try saying sport, local news, Swindon, Talking News Federation, or what's trending."
    )
    CARD_TITLE = "Hear - complete voice guide"
    CARD_OPENING = (
        "FIND AND BROWSE\n"
        "- Say a topic, place, creator, publication, or talking newspaper directly.\n"
        "- Sport.\n- Swindon.\n- Talking News Federation.\n"
        "- What's new?\n- What's trending?\n- Play the latest news.\n"
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
