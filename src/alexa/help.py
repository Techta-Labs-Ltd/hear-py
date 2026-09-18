from __future__ import annotations

from src.alexa.playback_speech import PlaybackSpeech


class HelpSpeech:
    BRIEF_GUIDE = (
        "Welcome to Hear. Search by topic, creator, city, publication, or talking newspaper. "
        "For example, say find content about the Roman Empire, set my city to Swindon, "
        "what's trending to hear popular content from across Hear, or play recommendations "
        "for something chosen for you. "
        "Would you like to hear more? Say yes or no."
    )
    GUIDE_OPENING = (
        "Here is your guide to Hear. Search by topic, creator, city, publication, or talking "
        "newspaper. For example, say find content about the Roman Empire, set my city to "
        "Swindon, what's trending to hear popular content from across Hear, or play "
        "recommendations for something chosen for you. When I read out choices, say the name "
        "or number, show more, previous choices, or none of these. "
    )
    GUIDE_CLOSING = (
        "To learn more, ask what's this about or who made this. You can "
        "follow or unfollow the creator, play content from creators you follow, rate the "
        "recording, or report inappropriate content. You can ask to hear your updates, or turn "
        "notifications on or off. To personalise Hear, say change my location or set up my "
        "account. For example, try saying local news. What would you like to hear?"
    )
    CONFIRMATION_REPROMPT = "Would you like to hear more? Say yes or no."
    REPROMPT = (
        "What would you like to hear? Try saying find content about the Roman Empire, set my "
        "city to Swindon, what's trending, or play recommendations."
    )
    CARD_TITLE = "Hear - complete voice guide"
    CARD_OPENING = (
        "FIND AND BROWSE\n"
        "- Search by topic, creator, city, publication, or talking newspaper.\n"
        "- Find content about the Roman Empire.\n"
        "- Set my city to Swindon.\n"
        "- What's trending? Hear popular content from across Hear.\n"
        "- Play recommendations for something chosen for you.\n"
        "- Play something about [topic].\n- Play from [creator or organisation].\n"
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
    def full_guide() -> str:
        return f"{HelpSpeech.GUIDE_OPENING}{PlaybackSpeech.help_guide()} {HelpSpeech.GUIDE_CLOSING}"

    @staticmethod
    def card_text(stage: str) -> str:
        return (
            f"{HelpSpeech.CARD_OPENING}{PlaybackSpeech.help_card_section(stage)}\n\n"
            f"{HelpSpeech.CARD_CLOSING}"
        )
