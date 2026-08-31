from __future__ import annotations

from src.utils.content import ContentUtils


class Speech:
    ONBOARDING_LOCATION_REASON = "Your location helps Hear find nearby news, sport, publications, and talking newspapers. Alexa will now ask whether you give Hear permission to use your location."
    LOCATION_PERMISSION_DENIED = "Location permission is currently turned off. You can enable it in the Alexa app, say the name of your city, or say skip to continue as a guest."
    LOCATION_PERMISSION_EMPTY = "Location permission is enabled, but I couldn't find a location saved for this device. Please say the name of your city, or say skip to continue as a guest."
    LOCATION_PERMISSION_UNAVAILABLE = "I couldn't check your device location right now. Please say the name of your city, or say skip to continue as a guest."
    PROFILE_PERMISSION_OFFER = "Would you like to share your name and email so I can setup your Hear listener profile? You can say yes or skip."
    PROFILE_PERMISSION_REASON = "Your name lets me personalise Hear, and your email identifies your listener account. Alexa will now ask whether you give Hear permission to share them."
    PROFILE_PERMISSION_SKIPPED = "No problem. You can continue using Hear as a guest. What would you like to listen to?"
    PROFILE_PERMISSION_FAILED = "I couldn't complete your listener account setup, so I'll keep you as a guest. You can say set up my account later. What would you like to listen to?"
    PROFILE_PERMISSION_COMPLETE = "Thanks. Your Hear listener account is ready. What would you like to listen to?"
    TOWN_SKIPPED = "Okay. What would you like to listen to?"
    TOWN_NOT_UNDERSTOOD = "I couldn't identify that city. Please say the full city name, or say skip to continue without one."
    TOWN_LOOKUP_UNAVAILABLE_RETRY = (
        "I can't check that city right now. Please try the city name again."
    )
    TOWN_LOOKUP_UNAVAILABLE_CONTINUE = "I still can't check cities, so I'll continue without your location. You can set it later. What would you like to listen to?"
    CITY_SETUP_GUIDANCE = "Sorry, I still couldn't identify your city. You can update Device Location for this Echo in the Alexa app and then relaunch Hear, try saying your city again, or say skip to continue."
    REPROMPT_NO_CITY = "Say the latest, what's popular, or what's on."
    REPROMPT_ASK_TOWN = "Which city are you in? You can also say skip."
    ONBOARDING_DEFER_CONTENT = "Happy to play that for you. First, which city are you in?"
    COMMUNITY_NEEDS_TOWN = (
        "I'll need your city to find local content. Would you like to set that up?"
    )
    WELCOME_REPROMPT = (
        "You can say play followed by a topic, or what's trending. What would you like?"
    )
    RESUME_DECLINED_NEXT_OPTIONS = "Okay, I won't continue that recording. You can ask for news or sport, play from a talking newspaper, or say what's trending. What would you like to listen to?"
    RESUME_DECLINED_NEXT_OPTIONS_REPROMPT = "You can ask for news or sport, play from a talking newspaper, or say what's trending. What would you like to listen to?"
    WELCOME_ERROR = "Welcome to Hear. I'm having a bit of trouble loading content at the moment. You can try again shortly."
    PLAYBACK_SPEED_NOT_SUPPORTED = "This recording does not have faster or slower versions. I can only play it at normal speed."
    PLAYBACK_SPEED_MAX = "This is the maximum speed."
    PLAYBACK_SPEED_MIN = "This is the minimum speed."
    PLAYBACK_SPEED_INVALID = "Say first through sixth speed, normal speed, faster, or slower."
    QUEUE_FINISHED = (
        "That was the last one. Say what's trending for popular tracks, or play something."
    )
    IDLE_NEXT_REPROMPT = "What would you like to listen to?"
    IDLE_DO_NEXT_REPROMPT = "What would you like to do next?"
    SEARCH_UNAVAILABLE = (
        "I'm having a bit of trouble reaching Hear right now. You can try again in a moment."
    )
    BROWSE_EXHAUSTED = "That's everything I found."
    ASK_TALKING_NEWSPAPER = "Which talking newspaper would you like?"
    ASK_TALKING_NEWSPAPER_REPROMPT = "Please say its name, for example York Talking News."
    NO_CONTENT_AVAILABLE = "There's no content available at the moment. You can try again shortly."
    CONTENT_NOT_READY = "That one isn't ready to play yet. Try another number."
    RESUMING = "Resuming where you left off."
    NOTHING_TO_RESUME = "Nothing to resume. Say what's trending, or play something to get started."
    REPLAYING = "Playing again from the start."
    PLAYING_PREVIOUS = "Playing the previous recording."
    NO_PREVIOUS = "There is no previous content to play."
    CANNOT_SEEK = "Nothing is playing right now. Say play to start listening."
    CREATOR_CREDIT_UNKNOWN = "I do not have creator information for the current content."
    FEEDBACK_FOLLOW_DECLINED = "No problem. What would you like to listen to next?"
    FEEDBACK_SOMEWHAT = "Thanks for the feedback — we'll use that to improve your recommendations. What would you like to listen to next?"
    FEEDBACK_NOT_ENJOYED = "Sorry to hear that. If you feel the content was inappropriate, say report this content and we'll flag it for review. Otherwise say skip to carry on."
    FEEDBACK_SKIP_INTRO = "No problem. What would you like to listen to next?"
    FEEDBACK_AWAITING_REPROMPT = (
        "Did you enjoy that track? Say enjoyed, it was okay, not enjoyed, or skip."
    )
    FEEDBACK_REPORT_REPROMPT = "Say report this content, or skip to continue."
    FOLLOW_CREATOR_REPROMPT = (
        "Say next to hear something else, or unfollow this creator to stop following."
    )
    NO_CREATOR_TO_FOLLOW = "There is no creator associated with the current content."
    NO_FOLLOWED_CREATORS_TO_PLAY = "You're not following any creators yet. Play something you enjoy and say follow this creator to get started."
    REPORT_CONTENT_CONFIRM = (
        "This content has been flagged for review. Thank you for helping keep Hear safe."
    )
    REPORT_CONTENT_THEN_ASK_CONTINUE = f"{REPORT_CONTENT_CONFIRM} Do you want to keep listening to this recording? Say yes to continue, or no to skip to something else."
    FLAGGED_CONTINUE_REPROMPT = "Say yes to keep listening, or no to skip to the next item."
    FLAGGED_CONTINUE_YES_ACK = "Okay, continuing."
    LAUNCH_RESUME_FLAGGED_PROMPT = "Do you want to keep listening to this recording? Say yes to continue, or no to skip to something else."
    REPORT_NOTHING_PLAYING = (
        "There is nothing playing right now to report. Play some content first."
    )
    PLAY_NO_PENDING_LIST = (
        "Say what's trending first, then pick the first one or say play number one."
    )
    FALLBACK_SPEECH = "Sorry, I didn't catch that. You can say play news, play from a creator by name, or what's trending. What would you like?"
    HELP = "Here's what you can do: say what's trending for popular tracks, play followed by a topic, or play from a talking newspaper by name. Rate tracks by saying enjoyed, it was okay, or not enjoyed. Would you like to try something?"
    GOODBYE = "Thanks for listening to Hear. Goodbye."
    ERROR_GENERIC = "Sorry, I didn't quite catch that. You can say play followed by a topic, or what's trending. What would you like?"
    LOOP_SHUFFLE_UNAVAILABLE = (
        "Looping and shuffle are not available on Hear yet. Say next, repeat, or pause."
    )
    NO_TRACKS_AVAILABLE = (
        "Welcome to Hear. There are no tracks available right now. Check back soon."
    )
    ONBOARDING_ASK_PERMISSION = "Welcome to Hear. I can bring you the latest audio from your local community — news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright?"
    ONBOARDING_CONSENT_CARD_SENT = "Please open the Alexa app, find test development under Your Skills, then open Settings and Manage Permissions and enable Device Address. After that, relaunch Hear."
    ONBOARDING_LOCATION_DENIED = "No worries. Which city are you in?"
    ONBOARDING_FETCHING_LOCATION = "Bear with me a second, just finding you on the map..."
    CONSENT_CARD_THANKS = "Thanks — you're all set. What would you like to listen to?"
    LOCATION_NOT_FOUND = "Welcome back to Hear. I don't have a city for this Echo yet. You can tell me your city now, or say skip. To use your Echo's saved location instead, update Device Location in the Alexa app and relaunch Hear."
    LOCATION_DECLINED = "No problem. What would you like to listen to?"
    LOCATION_RETRY = "No problem. Which city should I set instead?"
    WELCOME_RETURN_GENERIC = (
        "Welcome back to Hear. You can say what's trending, or play news. What would you like?"
    )
    LATEST_SOURCE_DECLINED = "No problem. You can ask for news or sport, play from a talking newspaper, or say what's trending. What would you like to listen to?"

    @staticmethod
    def _build_queue_next(title, creator, position, total):
        safe_title = Speech.humanize_spoken_title(title)
        safe_creator = Speech.escape_ssml_lite(creator) if creator else None
        pos = f" Track {position} of {total}." if total and total > 1 else ""
        if safe_title and safe_creator:
            return f"Next up: {safe_title}, by {safe_creator}.{pos}"
        if safe_title:
            return f"Next up: {safe_title}.{pos}"
        if safe_creator:
            return f"Next up: a recording by {safe_creator}.{pos}"
        return "Next up."

    @staticmethod
    def _build_content_about(title, summary, main_topic, creator) -> str:
        safe_title = Speech.humanize_spoken_title(title)
        safe_summary = Speech.escape_ssml_lite(summary) if summary else None
        safe_topic = Speech.escape_ssml_lite(main_topic) if main_topic else None
        safe_creator = (
            Speech.escape_ssml_lite(creator)
            if creator and (not Speech.is_bad_credit(creator))
            else None
        )
        if safe_summary:
            if safe_title:
                return f"{safe_title}. {safe_summary}"
            return safe_summary
        if safe_topic:
            if safe_title:
                return f"{safe_title} is about {safe_topic}."
            return f"This is about {safe_topic}."
        if safe_title and safe_creator:
            return f"I don't have a description for this one, but it's {safe_title}, by {safe_creator}."
        if safe_title:
            return f"I don't have a description for this one, but it's {safe_title}."
        return "I don't have a description for this recording."

    @staticmethod
    def build_now_playing_phrase(title, creator=None) -> str:
        """Build a 'Now playing: ...' phrase for the given title and optional creator."""
        safe = Speech.humanize_spoken_title(title)
        if safe and creator:
            return f"Now playing: {safe}, by {creator}."
        if safe:
            return f"Now playing: {safe}."
        if creator:
            return f"Now playing a recording by {creator}."
        return "Now playing the next recording."

    @staticmethod
    def _build_launch_pending(title, creator, user_name) -> str:
        greeting = (
            f"Welcome back, {Speech.escape_ssml_lite(user_name)}. Before we continue"
            if user_name
            else "Welcome back to Hear. Before we continue"
        )
        return f"{greeting} — did you enjoy {title} by {creator}? You can say enjoyed, it was okay, or not enjoyed. Say skip if you'd rather not rate it."

    @staticmethod
    def _build_enjoyed_following(title, creator_name) -> str:
        safe_title = (
            Speech.escape_ssml_lite(title)
            if title and (not Speech.is_bad_credit(title))
            else "that"
        )
        safe_creator = (
            Speech.escape_ssml_lite(creator_name)
            if creator_name and (not Speech.is_bad_credit(creator_name))
            else None
        )
        if safe_creator:
            return f"Thanks for your feedback on {safe_title} by {safe_creator}. What would you like to listen to next?"
        return f"Thanks for your feedback on {safe_title}. What would you like to listen to next?"

    @staticmethod
    def _build_community_intro(locality, total_hits) -> str:
        count = min(3, total_hits) if isinstance(total_hits, (int, float)) and total_hits > 0 else 3
        picks = "3 picks" if count == 3 else f"{count} picks"
        if locality:
            return f"Here are {picks} from your community in {Speech.escape_ssml_lite(locality)}."
        return f"Here are {picks} from your community."

    @staticmethod
    def escape_ssml_lite(s: str) -> str:
        """Escape a plain string for safe inclusion inside SSML."""
        s = str(s or "")
        result: list[str] = []
        for ch in s:
            code = ord(ch)
            if 0 <= code <= 8 or code == 11 or code == 12 or (14 <= code <= 31):
                continue
            if ch == "&":
                result.append(" and ")
            elif ch == "<":
                result.append(" ")
            elif ch == ">":
                result.append(" ")
            elif ch == '"':
                result.append("'")
            else:
                result.append(ch)
        return "".join(result)

    @staticmethod
    def humanize_spoken_title(raw_title) -> str | None:
        """Determine whether a raw title string is suitable for spoken output."""
        if not isinstance(raw_title, str):
            return None
        title = raw_title.strip()
        return None if ContentUtils.is_id_like_label(title) else title

    @staticmethod
    def is_bad_credit(value) -> bool:
        """Check whether a credit string is unsuitable for spoken output."""
        return ContentUtils.is_bad_credit_name(value)

    @staticmethod
    def WELCOME_FIRST_ASK_TOWN(name):
        return (
            f"Hello {Speech.escape_ssml_lite(name)}, welcome to Hear. Which city are you in?"
            if name
            else "Hello, welcome to Hear. Which city are you in?"
        )

    @staticmethod
    def WELCOME_FIRST_HAS_CITY(name, city=None):
        return (
            f"Hello {Speech.escape_ssml_lite(name)}, welcome to Hear. You can say what's trending, play news, or play from a creator. What would you like?"
            if name
            else "Hello, welcome to Hear. You can say what's trending, play news, or play from a creator. What would you like?"
        )

    @staticmethod
    def WELCOME_FIRST(name=None):
        return (
            f"Hello {Speech.escape_ssml_lite(name)}, welcome to Hear. You can say play news, or what's trending. What would you like?"
            if name
            else "Hello, welcome to Hear. You can say play news, or what's trending. What would you like?"
        )

    @staticmethod
    def TOWN_GOT_IT(city):
        return f"{Speech.escape_ssml_lite(city) or 'your area'} it is. What would you like to listen to?"

    @staticmethod
    def CITY_NOT_FOUND(city):
        return f"Sorry, I couldn't find {Speech.escape_ssml_lite(city)} as a city. Please say the city name again, or say skip to continue without local content."

    @staticmethod
    def REPROMPT_CITY(city):
        return f"Say the latest from {Speech.escape_ssml_lite(city) or 'your area'}, what's popular, or what's on."

    @staticmethod
    def PLAYBACK_SPEED_UNAVAILABLE(speed, available):
        return f"Speed {speed} is not available for this content. Available speeds are {available}."

    @staticmethod
    def PLAYBACK_SPEED_SET(speed):
        return (
            "Playback speed reset to normal."
            if speed == 1.0
            else f"Playback speed set to {speed}x."
        )

    @staticmethod
    def PLAYBACK_SPEED_SET_IDLE(speed):
        return (
            "Playback speed reset to normal. What would you like to listen to next?"
            if speed == 1.0
            else f"Playback speed set to {speed}x. What would you like to listen to next?"
        )

    @staticmethod
    def QUEUE_NEXT_ANNOUNCE(title, creator=None, position=None, total=None):
        return Speech._build_queue_next(title, creator, position, total)

    @staticmethod
    def CONTENT_ABOUT_PHRASE(title, summary=None, main_topic=None, creator=None):
        return Speech._build_content_about(title, summary, main_topic, creator)

    @staticmethod
    def LOCAL_CONTENT_FALLBACK(title, creator=None):
        return Speech.build_now_playing_phrase(title, creator)

    @staticmethod
    def REWOUND(seconds):
        return f"Rewound {seconds} seconds."

    @staticmethod
    def FAST_FORWARDED(seconds):
        return f"Skipped forward {seconds} seconds."

    @staticmethod
    def CREATOR_CREDIT(title, creator):
        return (
            f"You are listening to {Speech.humanize_spoken_title(title)}, created by {creator}."
            if Speech.humanize_spoken_title(title)
            else f"You are listening to a recording created by {creator}."
        )

    @staticmethod
    def LAUNCH_PENDING_FEEDBACK(title, creator, user_name=None):
        return Speech._build_launch_pending(title, creator, user_name)

    @staticmethod
    def FEEDBACK_ENJOYED_ALREADY_FOLLOWING(title, creator_name=None):
        return Speech._build_enjoyed_following(title, creator_name)

    @staticmethod
    def FEEDBACK_FOLLOW_ASK(creator_name):
        return f"Brilliant! Glad you enjoyed it. Would you like to follow {Speech.escape_ssml_lite(creator_name)}? You'll be notified whenever they publish something new. Say follow, or no thanks."

    @staticmethod
    def FEEDBACK_FOLLOW_REPROMPT(creator_name):
        return f"Say follow to follow {Speech.escape_ssml_lite(creator_name)}, or no thanks to continue."

    @staticmethod
    def FOLLOW_CREATOR(creator_name):
        return f"Done! You're now following {Speech.escape_ssml_lite(creator_name)}. If you'd like to hear something else, just say next."

    @staticmethod
    def ALREADY_FOLLOWING(creator_name):
        return f"You are already following {Speech.escape_ssml_lite(creator_name)}."

    @staticmethod
    def UNFOLLOW_CREATOR(creator_name):
        return f"Done. You've unfollowed {Speech.escape_ssml_lite(creator_name)}. What would you like to do next?"

    @staticmethod
    def NOT_FOLLOWING(creator_name):
        return f"You are not following {creator_name}."

    @staticmethod
    def REPORT_CREATOR_CONFIRM(creator_name):
        return f"Thank you. We've flagged {Speech.escape_ssml_lite(creator_name)}'s content for the Talking News Federation team to review. What would you like to listen to next?"

    @staticmethod
    def PLAY_COMMUNITY_INTRO(locality=None, total_hits=None):
        return Speech._build_community_intro(locality, total_hits)

    @staticmethod
    def ONBOARDING_DETECTED_TOWN(city):
        return f"I think you're in {Speech.escape_ssml_lite(city)} — is that right?"

    @staticmethod
    def ONBOARDING_TOWN_CONFIRM(city):
        return f"Did you say {Speech.escape_ssml_lite(city)}?"

    @staticmethod
    def ONBOARDING_DEVICE_TOWN_CONFIRM(city):
        return f"Your Alexa device location is set to {Speech.escape_ssml_lite(city)}. Should I use {Speech.escape_ssml_lite(city)} for your local content?"

    @staticmethod
    def COMMUNITY_PLAYBACK_OFFER(city):
        return f"Would you like to hear the latest from {Speech.escape_ssml_lite(city)}?"

    @staticmethod
    def LOCATION_CONFIRMED(city):
        return f"Thanks. I've set your location to {Speech.escape_ssml_lite(city)}. You can ask for local news or sport, play from a talking newspaper, or say what's trending. What would you like to hear?"

    @staticmethod
    def WELCOME_RETURN_NAMED(user_name, city=None):
        return f"Welcome back to Hear, {Speech.escape_ssml_lite(user_name)}. You can say what's trending, play news, or play from a talking newspaper. What would you like?"

    @staticmethod
    def WELCOME_RETURN_CITY(city=None):
        return "Welcome back to Hear. You can say what's trending, play news, or play from a talking newspaper. What would you like?"

    @staticmethod
    def LATEST_SOURCE_OFFER(source):
        return f"Welcome back to Hear. Would you like to hear the latest from {Speech.escape_ssml_lite(source)}?"

    @staticmethod
    def LATEST_SOURCE_REPROMPT(source):
        return f"Say yes to hear the latest from {Speech.escape_ssml_lite(source)}, or no to choose something else."
