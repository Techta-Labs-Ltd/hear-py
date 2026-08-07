from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.utils.normalize_content_item import is_bad_credit_name, is_id_like_label

_MAX_SSML_CHARS = 7500

ORDINAL_LABELS = [
    "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth",
    "Eleventh", "Twelfth", "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth", "Seventeenth",
    "Eighteenth", "Nineteenth", "Twentieth",
]


def ssml(text: str, pause_ms: int = 400) -> str:
    """Wrap text in SSML speak tags with a leading break."""
    return f"<speak><break time=\"{pause_ms}ms\"/>{text}</speak>"


def ssml_with_speed(text: str, speed: float = 1.0, pause_ms: int = 400) -> str:
    """Wrap text in SSML speak tags with a prosody rate applied."""
    percent = round(speed * 100)
    return f"<speak><break time=\"{pause_ms}ms\"/><prosody rate=\"{percent}%\">{text}</prosody></speak>"


def escape_ssml_lite(s: str) -> str:
    """Escape a plain string for safe inclusion inside SSML."""
    s = str(s or "")
    result: list[str] = []
    for ch in s:
        code = ord(ch)
        if 0 <= code <= 8 or code == 11 or code == 12 or 14 <= code <= 31:
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


def cap_ssml(ssml_text: str | None) -> str | None:
    """Truncate SSML text that exceeds the maximum allowed character length."""
    if not ssml_text or len(ssml_text) <= _MAX_SSML_CHARS:
        return ssml_text
    inner = ssml_text.replace("<speak>", "", 1).rsplit("</speak>", 1)[0]
    return f"<speak>{inner[:_MAX_SSML_CHARS - 20]}</speak>"


def ordinal_label(index: int) -> str:
    """Return the ordinal word label for a zero-based index."""
    if 0 <= index < len(ORDINAL_LABELS):
        return ORDINAL_LABELS[index]
    return str(index + 1)


def humanize_spoken_title(raw_title) -> str | None:
    """Determine whether a raw title string is suitable for spoken output."""
    if not isinstance(raw_title, str):
        return None
    title = raw_title.strip()
    if not title:
        return None
    if re.search(r"\d{3,}[_-]post", title, re.I):
        return None
    if re.search(r"[_-]post\d+", title, re.I):
        return None
    if re.search(r"track\d+", title, re.I) and re.search(r"post|_", title):
        return None
    if re.search(r"\s", title):
        return title
    if len(title) <= 12:
        return title
    if re.search(r"[_/\\\.:]", title):
        return None
    if re.search(r"\d{4,}", title):
        return None
    if re.match(r"^[a-z0-9-]+$", title, re.I) and re.search(r"\d", title) and len(title) > 16:
        return None
    return title


def resolve_spoken_creator_label(creator, store: dict | None) -> str | None:
    """Resolve a creator id/name into a speakable label, consulting the session store."""
    if not creator:
        return None
    raw = str(creator).strip()
    if not raw:
        return None
    if not is_bad_credit_name(raw) and not is_id_like_label(raw):
        return raw
    store = store or {}
    for c in store.get("followedCreators") or []:
        if c.get("id") == raw:
            nm = c.get("name")
            if nm and not is_bad_credit_name(nm):
                return nm
    if store.get("feedbackCreatorId") == raw:
        fc = store.get("feedbackCreator")
        if fc and not is_bad_credit_name(fc):
            return fc
    if store.get("currentCreatorId") == raw:
        cc = store.get("currentCreator")
        if cc and not is_bad_credit_name(cc):
            return cc
    return None


def is_bad_credit(value) -> bool:
    """Check whether a credit string is unsuitable for spoken output."""
    return is_bad_credit_name(value)


# ── Welcome / Onboarding ───────────────────────────────────────────

WELCOME_FIRST_ASK_TOWN = lambda name: (
    f"Hello {escape_ssml_lite(name)}, welcome to Hear. Which town or city are you in?"
    if name else "Hello, welcome to Hear. Which town or city are you in?"
)

WELCOME_FIRST_HAS_CITY = lambda name, city=None: (
    f"Hello {escape_ssml_lite(name)}, welcome to Hear. You can say what's trending, play news, or play from a creator. What would you like?"
    if name else "Hello, welcome to Hear. You can say what's trending, play news, or play from a creator. What would you like?"
)

WELCOME_RETURN = lambda name=None: "Welcome back to Hear. You can say play news, or what's trending. What would you like?"

WELCOME_FIRST = lambda name=None: (
    f"Hello {escape_ssml_lite(name)}, welcome to Hear. You can say play news, or what's trending. What would you like?"
    if name else "Hello, welcome to Hear. You can say play news, or what's trending. What would you like?"
)

TOWN_GOT_IT = lambda city: f"{escape_ssml_lite(city) or 'your area'} it is. What would you like to listen to?"

TOWN_SKIPPED = "Okay. What would you like to listen to?"

TOWN_NOT_UNDERSTOOD = "Just the town name please — like London or Manchester. Or say skip if you'd rather not."
TOWN_LOOKUP_UNAVAILABLE_RETRY = "I can't check towns right now. Please say your town once more, or say skip."
TOWN_LOOKUP_UNAVAILABLE_CONTINUE = "I still can't check towns, so I'll continue without your location. You can set it later. What would you like to listen to?"

TOWN_HELP = "Just say your town name, like London or Manchester. Or say skip."

HOW_IT_WORKS_CITY = lambda city: (
    f"What would you like \u2014 the latest from {escape_ssml_lite(city) or 'your area'}, what's popular, or what's on?"
)

HOW_IT_WORKS = "What would you like \u2014 the latest, what's popular, or what's on?"

REPROMPT_CITY = lambda city: (
    f"Say the latest from {escape_ssml_lite(city) or 'your area'}, what's popular, or what's on."
)

REPROMPT_NO_CITY = "Say the latest, what's popular, or what's on."

REPROMPT_ASK_TOWN = "Where are you based? Or say skip."

ONBOARDING_DEFER_CONTENT = "Happy to play that for you. First, which town or city are you in? Or say skip."

HELP_ONBOARDING = "You can say the latest, what's popular, what's on, or things like play news and play sport."

COMMUNITY_NEEDS_TOWN = "I'll need your town to find local content. Would you like to set that up?"

WELCOME_REPROMPT = "You can say play followed by a topic, or what's trending. What would you like?"

RESUME_DECLINED_NEXT_OPTIONS = (
    "Okay, I won't continue that recording. You can ask for news or sport, "
    "play from a talking newspaper, or say what's trending. "
    "What would you like to listen to?"
)

RESUME_DECLINED_NEXT_OPTIONS_REPROMPT = (
    "You can ask for news or sport, play from a talking newspaper, "
    "or say what's trending. What would you like to listen to?"
)

LAUNCH_CHOICE_OUTRO = "Say the first one, the second one, or the third one. You can also say play number one, play number two, or play number three."

WELCOME_ERROR = "Welcome to Hear. I'm having a bit of trouble loading content at the moment. You can try again shortly."

# ── Playback Speed ──────────────────────────────────────────────────

PLAYBACK_SPEED_NOT_SUPPORTED = "This recording does not have faster or slower versions. I can only play it at normal speed."
PLAYBACK_SPEED_UNAVAILABLE = lambda speed, available: f"Speed {speed} is not available for this content. Available speeds are {available}."
PLAYBACK_SPEED_FALLBACK_DEFAULT = lambda speed: f"Speed {speed}x isn't available for this recording. Playing at normal speed."
PLAYBACK_SPEED_MAX = "This is the maximum speed."
PLAYBACK_SPEED_MIN = "This is the minimum speed."

PLAYBACK_SPEED_SET = lambda speed: f"Playback speed set to {speed}x."
PLAYBACK_SPEED_INVALID = "Supported speeds are 0.5, 0.75, 1, 1.25, 1.5, and 2. Which would you like?"

# ── Queue / Browse ──────────────────────────────────────────────────

QUEUE_NEXT_ANNOUNCE = lambda title, creator=None, position=None, total=None: _build_queue_next(title, creator, position, total)


def _build_queue_next(title, creator, position, total):
    safe_title = humanize_spoken_title(title)
    safe_creator = escape_ssml_lite(creator) if creator else None
    pos = f" Track {position} of {total}." if total and total > 1 else ""
    if safe_title and safe_creator:
        return f"Next up: {safe_title}, by {safe_creator}.{pos}"
    if safe_title:
        return f"Next up: {safe_title}.{pos}"
    if safe_creator:
        return f"Next up: a recording by {safe_creator}.{pos}"
    return "Next up."


QUEUE_FINISHED = "That was the last one. Say what's trending for popular tracks, or play something."

STILL_LISTENING_PROMPT = "You've been listening for a while. Would you like to keep going?"
STILL_LISTENING_REPROMPT = "Say yes to keep listening, or no to stop."

IDLE_NEXT_REPROMPT = "What would you like to listen to?"
IDLE_DO_NEXT_REPROMPT = "What would you like to do next?"

# ── Search ──────────────────────────────────────────────────────────

SEARCH_PLAYING = lambda total, title, creator: (
    f"I found {total} stories. Now playing {escape_ssml_lite(title)}, by {escape_ssml_lite(creator)}."
)
SEARCH_PLAYING_NO_CREDIT = lambda total, title: (
    f"I found {total} stories. Now playing {escape_ssml_lite(title)}."
)
SEARCH_PLAYING_UNTITLED = lambda total: (
    f"I found {total} stories. Now playing the first one."
)


def _build_search_relaxed(query) -> str:
    safe = escape_ssml_lite(str(query).strip()) if query else ""
    tail = " Here are some other picks for you."
    if safe:
        return f"I could not find anything for {safe}.{tail}"
    return f"I could not find an exact match.{tail}"


SEARCH_RELAXED_INTRO = lambda query: _build_search_relaxed(query)


def _build_search_no_match(query) -> str:
    safe = escape_ssml_lite(str(query).strip()) if query else ""
    if safe:
        return f"I couldn't find anything for {safe} right now. You could try a different topic, or say what's trending. What would you like?"
    return "I couldn't find anything right now. You could try a different topic, or say what's trending. What would you like?"


SEARCH_NO_MATCH = lambda query: _build_search_no_match(query)


def unresolved_reference_message(phrase: str, expected_types: list[str]) -> str:
    safe = escape_ssml_lite(str(phrase).strip())
    labels = {
        "creator": "creator",
        "organization": "organisation",
        "publication": "publication",
        "location": "place",
    }
    expected = [labels[value] for value in expected_types if value in labels]
    kind = (
        f"{', '.join(expected[:-1])} or {expected[-1]}"
        if len(expected) > 1
        else expected[0] if expected
        else "name"
    )
    return (
        f"I couldn't find a {kind} named {safe}. "
        "Please try the full name, or ask for a different one."
    )


def ambiguous_reference_message(phrase: str, candidates: list[dict]) -> str:
    names = list(dict.fromkeys(
        escape_ssml_lite(str(item.get("name") or "").strip())
        for item in candidates
        if item.get("name")
    ))[:3]
    if not names:
        return unresolved_reference_message(phrase, [])
    raw_names = [str(item.get("name") or "").strip() for item in candidates if item.get("name")][:3]
    word_lists = [name.split() for name in raw_names]
    common = []
    for words in zip(*word_lists):
        if len({word.casefold() for word in words}) != 1:
            break
        common.append(words[0])
    if common and len(raw_names) > 1:
        prefix = " ".join(common)
        suffixes = [name[len(prefix):].strip(" ,-â€“—") for name in raw_names]
        suffixes = [escape_ssml_lite(value) for value in suffixes if value]
        if len(suffixes) == len(raw_names):
            choices = f"{', '.join(suffixes[:-1])}, or {suffixes[-1]}"
            return (
                f"I found several matches beginning {escape_ssml_lite(prefix)}. "
                f"Please say the distinguishing part: {choices}."
            )
    if len(names) == 1:
        choices = names[0]
    else:
        choices = f"{', '.join(names[:-1])}, or {names[-1]}"
    return (
        "I found more than one match for that name. "
        f"Did you mean {choices}?"
    )


def ambiguity_retry_message(candidates: list[dict]) -> str:
    return (
        "That did not match the available choices. "
        f"{ambiguous_reference_message('that name', candidates)} "
        "You can also say show more."
    )


def ambiguity_exhausted_message(candidates: list[dict]) -> str:
    return (
        "Those are all the matches I found. "
        f"{ambiguous_reference_message('that name', candidates)}"
    )


SEARCH_UNAVAILABLE = "I'm having a bit of trouble reaching Hear right now. You can try again in a moment."

# ── Browse / Catalog ────────────────────────────────────────────────

def TRENDING_INTRO(count, title=None, credit=None) -> str:
    total = max(0, int(count or 0))
    noun = "story" if total == 1 else "stories"
    intro = f"I found {total} trending {noun}."
    safe_title = escape_ssml_lite(str(title).strip()) if title else ""
    safe_credit = escape_ssml_lite(str(credit).strip()) if credit else ""
    if safe_title and safe_credit:
        return f"{intro} Now playing {safe_title}, by {safe_credit}."
    if safe_title:
        return f"{intro} Now playing {safe_title}."
    return f"{intro} Now playing the first one."
BROWSE_INTRO = lambda: "Here is what is available on Hear right now."
BROWSE_CATEGORY_INTRO = lambda category: f"Here is what is available in {escape_ssml_lite(category or '')}."
BROWSE_EXHAUSTED = "That's everything I found."
ASK_TALKING_NEWSPAPER = "Which talking newspaper would you like?"
ASK_TALKING_NEWSPAPER_REPROMPT = (
    "Please say its name, for example York Talking News."
)
TALKING_NEWSPAPER_NOT_RECOGNIZED = lambda name: (
    f"I couldn't match {escape_ssml_lite(name or 'that name')} to a talking "
    "newspaper. Please say the full name."
)
CONFIRM_TALKING_NEWSPAPER = lambda name: (
    f"Did you mean {escape_ssml_lite(name or 'that talking newspaper')}?"
)


def _spoken_date(value: datetime, *, include_year: bool = True) -> str:
    label = f"{value.day} {value.strftime('%B')}"
    return f"{label} {value.year}" if include_year else label


def _published_period_label(slots: dict) -> str:
    original = str(slots.get("temporalOriginal") or "").strip()
    if original:
        if re.match(r"^(?:on|from|since)\b", original, re.I):
            return original
        if re.match(r"^\d{1,2}\s+[A-Za-z]+\s+\d{4}$", original):
            return f"on {original}"
        return original

    search_plan = slots.get("searchPlan") or {}
    filters = search_plan.get("filter") or {}
    start_value = filters.get("publishedFrom", search_plan.get("publishedFrom"))
    end_value = filters.get("publishedTo", search_plan.get("publishedTo"))
    if not isinstance(start_value, (int, float)) or not isinstance(
        end_value, (int, float)
    ):
        return ""
    try:
        start = datetime.fromtimestamp(start_value, timezone.utc)
        end = datetime.fromtimestamp(end_value, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return ""
    if end <= start:
        return ""
    if end - start <= timedelta(days=1):
        return f"on {_spoken_date(start)}"
    if (
        start.day == 1
        and end.day == 1
        and end == (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12 else start.replace(month=start.month + 1)
        )
    ):
        return f"in {start.strftime('%B %Y')}"
    last_day = end - timedelta(days=1)
    if start.year == last_day.year:
        return (
            f"from {_spoken_date(start, include_year=False)} to "
            f"{_spoken_date(last_day)}"
        )
    return f"from {_spoken_date(start)} to {_spoken_date(last_day)}"


def resolved_search_request_label(slots: dict, source_name: str | None = None) -> str:
    """Build the complete spoken interpretation of a resolved search."""
    facets = []
    category = str(slots.get("category") or "").strip()
    if category:
        facets.append(category.replace("-", " "))
    for tag in slots.get("tags") or []:
        spoken = str(tag or "").strip().replace("-", " ")
        if spoken and spoken not in facets:
            facets.append(spoken)
    residual = str(slots.get("residualQuery") or "").strip()
    if residual:
        facets.append(residual)
    if category and residual:
        category_label = category.replace("-", " ")
        tag_labels = [
            str(tag).replace("-", " ")
            for tag in slots.get("tags") or []
            if str(tag or "").strip()
        ]
        subject = " and ".join([category_label, *tag_labels])
        subject = f"{subject} {residual}"
    else:
        subject = " and ".join(facets) or (
            "publication" if slots.get("isPublication") else "content"
        )
    if slots.get("latest"):
        subject = f"the latest {subject}"
    has_creator = bool(slots.get("creatorIds"))
    has_organization = bool(slots.get("organizationIds"))
    has_publication = bool(slots.get("publicationIds"))
    source = str(
        slots.get("organizationName")
        or slots.get("creatorName")
        or (source_name if has_creator or has_organization else "")
        or ""
    ).strip()
    if source:
        subject = f"{subject} from {source}"
    publication = str(
        slots.get("publicationName")
        or (source_name if has_publication and not source else "")
        or ""
    ).strip()
    if publication:
        subject = f"{subject} within {publication}"
    city = str(slots.get("city") or slots.get("placeName") or "").strip()
    if city:
        subject = f"{subject} in {city}"
    elif slots.get("isLocal"):
        subject = f"{subject} from your community"
    published_period = _published_period_label(slots)
    if published_period:
        subject = f"{subject} published {published_period}"
    return subject


CONFIRM_RESOLVED_SEARCH = lambda label: (
    f"Did you want me to play {escape_ssml_lite(label or 'that')}?"
)

CONTENT_ABOUT_PHRASE = lambda title, summary=None, main_topic=None, creator=None: _build_content_about(title, summary, main_topic, creator)


def _build_content_about(title, summary, main_topic, creator) -> str:
    safe_title = humanize_spoken_title(title)
    safe_summary = escape_ssml_lite(summary) if summary else None
    safe_topic = escape_ssml_lite(main_topic) if main_topic else None
    safe_creator = escape_ssml_lite(creator) if creator and not is_bad_credit(creator) else None
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


def build_now_playing_phrase(title, creator=None) -> str:
    """Build a 'Now playing: ...' phrase for the given title and optional creator."""
    safe = humanize_spoken_title(title)
    if safe and creator:
        return f"Now playing: {safe}, by {creator}."
    if safe:
        return f"Now playing: {safe}."
    if creator:
        return f"Now playing a recording by {creator}."
    return "Now playing the next recording."


LOCAL_CONTENT_FOUND = lambda locality, title, creator: f"Here is the latest from {locality}. {build_now_playing_phrase(title, creator)}"
LOCAL_CONTENT_FALLBACK = lambda title, creator=None: build_now_playing_phrase(title, creator)

NO_CONTENT_AVAILABLE = "There's no content available at the moment. You can try again shortly."
CONTENT_NOT_READY = "That one isn't ready to play yet. Try another number."

CATEGORY_PLAYING = lambda category, title, creator: f"Playing {category}. {build_now_playing_phrase(title, creator)}"
CATEGORY_NOT_FOUND = lambda category: f"Sorry, I could not find any {category} content right now."
CATEGORY_PROMPT = "Which category would you like? Try news, sports, entertainment, weather, or community."

POST_TRACK_BROWSE_INTRO = lambda: "That has finished. Here is what is available."

# ── Resume / Seek ───────────────────────────────────────────────────

RESUMING = "Resuming where you left off."
NOTHING_TO_RESUME = "Nothing to resume. Say what's trending, or play something to get started."

REWOUND = lambda seconds: f"Rewound {seconds} seconds."
FAST_FORWARDED = lambda seconds: f"Skipped forward {seconds} seconds."
REPLAYING = "Playing again from the start."
PLAYING_PREVIOUS = lambda title: f"Playing previous: {humanize_spoken_title(title)}." if humanize_spoken_title(title) else "Playing the previous recording."
NO_PREVIOUS = "There is no previous content to play."
CANNOT_SEEK = "Nothing is playing right now. Say play to start listening."

# ── Multi-Track ─────────────────────────────────────────────────────

TRACK_PLAYING = lambda track_num, total_tracks, track_title: _build_track_playing(track_num, total_tracks, track_title)


def _build_track_playing(track_num, total_tracks, track_title) -> str:
    safe = humanize_spoken_title(track_title)
    if safe:
        return f"Track {track_num} of {total_tracks}: {safe}."
    return f"Track {track_num} of {total_tracks}."


CREATOR_CREDIT = lambda title, creator: (
    f"You are listening to {humanize_spoken_title(title)}, created by {creator}."
    if humanize_spoken_title(title)
    else f"You are listening to a recording created by {creator}."
)
CREATOR_CREDIT_UNKNOWN = "I do not have creator information for the current content."

# ── Feedback ────────────────────────────────────────────────────────

ENJOYMENT_PROMPTS = [
    "Are you enjoying this so far?",
    "How are you finding this content?",
    "Is this hitting the spot for you?",
    "Enjoying what you are listening to?",
]

CATEGORY_INTEREST_PROMPTS = [
    lambda cat: f"Would you like more {cat} content?",
    lambda cat: f"Are you enjoying this {cat} content?",
    lambda cat: f"Is {cat} a category you would like more of?",
    lambda cat: f"Finding this {cat} content useful?",
]

SHORT_ENJOYMENT_PROMPTS = [
    "Enjoying this?",
    "How is this so far?",
]


def get_mid_playback_prompt(category=None, play_count: int = 0, duration_secs=None) -> str:
    """Return a mid-playback feedback prompt appropriate for the current context."""
    if isinstance(duration_secs, (int, float)) and duration_secs < 30:
        return SHORT_ENJOYMENT_PROMPTS[play_count % len(SHORT_ENJOYMENT_PROMPTS)]
    if play_count % 2 == 0:
        return ENJOYMENT_PROMPTS[play_count % len(ENJOYMENT_PROMPTS)]
    fn = CATEGORY_INTEREST_PROMPTS[play_count % len(CATEGORY_INTEREST_PROMPTS)]
    return fn(category or "this")


FEEDBACK_AFTER_TRACK = lambda title, creator: f"Did you enjoy {title} by {creator}? Say enjoyed, it was okay, not enjoyed, or skip."


def _build_launch_pending(title, creator, user_name) -> str:
    greeting = f"Welcome back, {escape_ssml_lite(user_name)}. Before we continue" if user_name else "Welcome back to Hear. Before we continue"
    return f"{greeting} \u2014 did you enjoy {title} by {creator}? You can say enjoyed, it was okay, or not enjoyed. Say skip if you'd rather not rate it."


LAUNCH_PENDING_FEEDBACK = lambda title, creator, user_name=None: _build_launch_pending(title, creator, user_name)


def _build_enjoyed_following(title, creator_name) -> str:
    safe_title = escape_ssml_lite(title) if (title and not is_bad_credit(title)) else "that"
    safe_creator = escape_ssml_lite(creator_name) if (creator_name and not is_bad_credit(creator_name)) else None
    if safe_creator:
        return f"Thanks for your feedback on {safe_title} by {safe_creator}. What would you like to listen to next?"
    return f"Thanks for your feedback on {safe_title}. What would you like to listen to next?"


FEEDBACK_ENJOYED_ALREADY_FOLLOWING = lambda title, creator_name=None: _build_enjoyed_following(title, creator_name)

FEEDBACK_FOLLOW_ASK = lambda creator_name: f"Brilliant! Glad you enjoyed it. Would you like to follow {escape_ssml_lite(creator_name)}? You'll be notified whenever they publish something new. Say follow, or no thanks."

FEEDBACK_FOLLOW_REPROMPT = lambda creator_name: f"Say follow to follow {escape_ssml_lite(creator_name)}, or no thanks to continue."

FEEDBACK_FOLLOW_DECLINED = "No problem. What would you like to listen to next?"

FEEDBACK_SOMEWHAT = "Thanks for the feedback \u2014 we'll use that to improve your recommendations. What would you like to listen to next?"

FEEDBACK_NOT_ENJOYED = "Sorry to hear that. If you feel the content was inappropriate, say report this content and we'll flag it for review. Otherwise say skip to carry on."

FEEDBACK_SKIP_INTRO = "No problem. What would you like to listen to next?"

FEEDBACK_AWAITING_REPROMPT = "Did you enjoy that track? Say enjoyed, it was okay, not enjoyed, or skip."
FEEDBACK_REPROMPT = FEEDBACK_AWAITING_REPROMPT
FEEDBACK_REPORT_REPROMPT = "Say report this content, or skip to continue."
FEEDBACK_REMINDER_SPOKEN = "Open Hear to rate what you were listening to."
SKIP_FEEDBACK = FEEDBACK_SKIP_INTRO

# ── Follow / Unfollow ───────────────────────────────────────────────

FOLLOW_CREATOR = lambda creator_name: f"Done! You're now following {escape_ssml_lite(creator_name)}. If you'd like to hear something else, just say next."

FOLLOW_CREATOR_REPROMPT = "Say next to hear something else, or unfollow this creator to stop following."

ALREADY_FOLLOWING = lambda creator_name: f"You are already following {escape_ssml_lite(creator_name)}."

UNFOLLOW_CREATOR = lambda creator_name: f"Done. You've unfollowed {escape_ssml_lite(creator_name)}. What would you like to do next?"

NOT_FOLLOWING = lambda creator_name: f"You are not following {creator_name}."

NO_CREATOR_TO_FOLLOW = "There is no creator associated with the current content."

NO_FOLLOWED_CREATORS_TO_PLAY = "You're not following any creators yet. Play something you enjoy and say follow this creator to get started."

# ── Report ──────────────────────────────────────────────────────────

REPORT_CONTENT_CONFIRM = "This content has been flagged for review. Thank you for helping keep Hear safe."
REPORT_CONTENT_THEN_ASK_CONTINUE = f"{REPORT_CONTENT_CONFIRM} Do you want to keep listening to this recording? Say yes to continue, or no to skip to something else."
FLAGGED_CONTINUE_REPROMPT = "Say yes to keep listening, or no to skip to the next item."
FLAGGED_CONTINUE_YES_ACK = "Okay, continuing."
LAUNCH_RESUME_FLAGGED_PROMPT = "Do you want to keep listening to this recording? Say yes to continue, or no to skip to something else."
REPORT_CREATOR_CONFIRM = lambda creator_name: f"Thank you. We've flagged {escape_ssml_lite(creator_name)}'s content for the Talking News Federation team to review. What would you like to listen to next?"
REPORT_NOTHING_PLAYING = "There is nothing playing right now to report. Play some content first."

# ── Permissions / Notifications ─────────────────────────────────────

ADDRESS_PERMISSION_REQUEST = "To provide you with local audio, Hear needs your permission to access your device address. I have sent a card to your Alexa app. Please open it to grant permission and try again."
LOCAL_GEO_PERMISSION_REQUEST = "To hear recordings from your community, enable location for Hear in the Alexa app. I have sent a card to your Alexa app."
LOCAL_GEO_REQUIRED = "To hear recordings from your community, enable location and device address for Hear in the Alexa app, then say play community again."

# ── Playback / Error ────────────────────────────────────────────────

PLAYBACK_FAILED = "There was a problem playing that content. Let me find something else for you."

# ── Play / List ─────────────────────────────────────────────────────

PLAY_CHOICE_REMINDER = "Which one would you like? Say play number one, play number two, or play the first one, second one, and so on."


def _build_community_intro(locality, total_hits) -> str:
    count = min(3, total_hits) if isinstance(total_hits, (int, float)) and total_hits > 0 else 3
    picks = "3 picks" if count == 3 else f"{count} picks"
    if locality:
        return f"Here are {picks} from your community in {escape_ssml_lite(locality)}."
    return f"Here are {picks} from your community."


PLAY_COMMUNITY_INTRO = lambda locality=None, total_hits=None: _build_community_intro(locality, total_hits)

PLAY_CHOICE_INVALID = "That number isn't in the list. Say show me more, or pick a number you heard."
PLAY_LIST_REPROMPT = "Which one would you like? Say the first one, the second one, or the third one."
PLAY_NO_PENDING_LIST = "Say what's trending first, then pick the first one or say play number one."
PLAY_CREATOR_PROMPT = "Which creator would you like to hear?"
PLAY_PICK_FROM_LIST_INTRO = "Here's what I found. Say the first one, the second one, or play number one."

# ── Fallback / Help / Generic ───────────────────────────────────────

FALLBACK_SPEECH = "Sorry, I didn't catch that. You can say play news, play from a creator by name, or what's trending. What would you like?"

HELP = (
    "Here's what you can do: say what's trending for popular tracks, play followed by a topic, "
    "or play from a talking newspaper by name. Rate tracks by saying enjoyed, it was okay, or not enjoyed. "
    "Would you like to try something?"
)

GOODBYE = "Thanks for listening to Hear. Goodbye."
ERROR_GENERIC = "Sorry, I didn't quite catch that. You can say play followed by a topic, or what's trending. What would you like?"
LOOP_SHUFFLE_UNAVAILABLE = "Looping and shuffle are not available on Hear yet. Say next, repeat, or pause."

# ── Notifications Summary ───────────────────────────────────────────


WELCOME_AUTOPLAY = lambda title, creator: f"Welcome to Hear. Playing {escape_ssml_lite(title)} by {escape_ssml_lite(creator)}."
WELCOME_RESUME = lambda title: f"Welcome back. Resuming {escape_ssml_lite(title)} where you left off."

ASK_LISTEN_FIRST = lambda title, creator, category, org: f"Welcome to Hear. Here is the first track. {escape_ssml_lite(title)} by {escape_ssml_lite(creator)}, {escape_ssml_lite(category)} from {escape_ssml_lite(org)}. Would you like to listen?"
ASK_LISTEN_NEXT = lambda title, creator, category: f"OK. Here is the next one. {escape_ssml_lite(title)} by {escape_ssml_lite(creator)}, {escape_ssml_lite(category)}. Would you like to listen?"
END_OF_LIST = "That is all the available tracks. Say start over to hear the list again, or stop to exit."
NO_TRACKS_AVAILABLE = "Welcome to Hear. There are no tracks available right now. Check back soon."

# ── Onboarding ──────────────────────────────────────────────────────

ONBOARDING_ASK_PERMISSION = "Welcome to Hear. I can bring you the latest audio from your local community \u2014 news, sport, talking newspapers and more. To get started, I'll need your location. Would that be alright?"
ONBOARDING_CONSENT_CARD_SENT = "I've sent a card to your Alexa app \u2014 open it and tap to share your location. If you'd rather not, you can just tell me your town and I'll take it from there."
ONBOARDING_LOCATION_DENIED = "No worries. Which town or city are you in?"
ONBOARDING_FETCHING_LOCATION = "Bear with me a second, just finding you on the map..."
ONBOARDING_DETECTED_TOWN = lambda city: f"I think you're in {escape_ssml_lite(city)} \u2014 is that right?"
ONBOARDING_TOWN_CONFIRM = lambda city: f"Did you say {escape_ssml_lite(city)}?"
ONBOARDING_TOWN_RETRY = "Sorry, didn\u2019t quite catch that. Say your town or city again."
ONBOARDING_TOWN_GIVE_UP = "I'm having trouble catching that. Not to worry \u2014 you can still browse everything. Say what's trending to get started. What would you like?"
CONSENT_CARD_THANKS = "Thanks \u2014 you're all set. What would you like to listen to?"
COMMUNITY_PLAYBACK_OFFER = lambda city: f"Would you like to hear the latest from {escape_ssml_lite(city)}?"

# \u2500\u2500 Location (set / confirm / resolution failure) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
LOCATION_NOT_FOUND = "I couldn't find your location from your account. Would you like to tell me which city you're in so I can find content from your area?"
LOCATION_ASK_CITY = "Which town or city are you in?"
LOCATION_DECLINED = "No problem. What would you like to listen to?"
LOCATION_CONFIRMED = lambda city: (
    f"Thanks. I've set your location to {escape_ssml_lite(city)}. "
    "You can ask for local news or sport, play from a talking newspaper, "
    "or say what's trending. What would you like to hear?"
)
LOCATION_RETRY = "No problem. Which city should I set instead?"
ONBOARDING_DISCOVERY = lambda city, count: f"Right, so you\u2019re near {escape_ssml_lite(city)} \u2014 nice one. I\u2019ve got {count} channels from your local community on here. You can ask for what\u2019s on in {escape_ssml_lite(city)}, pick a category like news or sport, or play from a local talking newspaper. What would you like to listen to?"
ONBOARDING_NO_LOCAL_CONTENT = lambda city: f"So you\u2019re near {escape_ssml_lite(city)} \u2014 got it. No local channels in your area just yet, but there\u2019s loads from communities all over the country. Ask for news or sport, play from a talking newspaper, or say what\u2019s trending. What would you like to listen to?"
ONBOARDING_DISCOVERY_NATIONAL = "Right, you\u2019re all set. Ask for news or sport, play from a talking newspaper, or say what\u2019s trending and I\u2019ll find something for you. What would you like to listen to?"

# ── Welcome Return ──────────────────────────────────────────────────

WELCOME_RETURN_NAMED = lambda user_name, city=None: f"Welcome back to Hear, {escape_ssml_lite(user_name)}. You can say what's trending, play news, or play from a talking newspaper. What would you like?"
WELCOME_RETURN_CITY = lambda city=None: "Welcome back to Hear. You can say what's trending, play news, or play from a talking newspaper. What would you like?"
WELCOME_RETURN_GENERIC = "Welcome back to Hear. You can say what's trending, or play news. What would you like?"
LATEST_SOURCE_OFFER = lambda source: f"Welcome back to Hear. Would you like to hear the latest from {escape_ssml_lite(source)}?"
LATEST_SOURCE_REPROMPT = lambda source: f"Say yes to hear the latest from {escape_ssml_lite(source)}, or no to choose something else."
LATEST_SOURCE_DECLINED = "No problem. You can ask for news or sport, play from a talking newspaper, or say what's trending. What would you like to listen to?"

# ── Confirm ─────────────────────────────────────────────────────────

CONFIRM_SINGLE = lambda name: f"Did you say {escape_ssml_lite(name)}?"
CONFIRM_NO = "Sorry, say it again."
CONFIRM_NO_MATCH = "Sorry, I didn\u2019t catch that. Say a category, a creator, or a town."

# End of speech catalog.

# ── Notification Detail ─────────────────────────────────────────────

