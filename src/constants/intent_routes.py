from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntentRouteRule:
    intent_name: str
    family: str
    rule_name: str
    priority: int
    expression: re.Pattern[str]
    slots: tuple[tuple[str, str], ...] = ()
    slot_name: str | None = None
    capture_name: str | None = None
    search: bool = False
    bypass_resolver: bool = True

    def match(self, phrase: str) -> tuple[tuple[str, str], ...] | None:
        matcher = self.expression.search if self.search else self.expression.fullmatch
        match = matcher(phrase)
        if not match:
            return None
        if not self.slot_name or not self.capture_name:
            return self.slots
        value = str(match.group(self.capture_name) or "").strip()
        return self.slots + ((self.slot_name, value),) if value else self.slots


def _rule(
    intent_name: str,
    family: str,
    rule_name: str,
    priority: int,
    expression: str,
    *,
    slots: tuple[tuple[str, str], ...] = (),
    slot_name: str | None = None,
    capture_name: str | None = None,
    search: bool = False,
    bypass_resolver: bool = True,
) -> IntentRouteRule:
    return IntentRouteRule(
        intent_name,
        family,
        rule_name,
        priority,
        re.compile(expression),
        slots,
        slot_name,
        capture_name,
        search,
        bypass_resolver,
    )


INTENT_ROUTE_RULES = tuple(
    sorted(
        (
            _rule(
                "AMAZON.PauseIntent",
                "transport",
                "pause",
                1200,
                r"(?:pause|pause playback|pause this)",
            ),
            _rule(
                "AMAZON.ResumeIntent",
                "transport",
                "resume",
                1200,
                r"(?:resume|continue|continue playing)",
            ),
            _rule(
                "AMAZON.StopIntent",
                "transport",
                "stop",
                1200,
                r"(?:stop|stop playing|stop playback)",
            ),
            _rule(
                "AMAZON.NextIntent",
                "transport",
                "next",
                1200,
                r"(?:next|next recording|skip this recording)",
            ),
            _rule(
                "AMAZON.PreviousIntent",
                "transport",
                "previous",
                1200,
                r"(?:previous|previous recording)",
            ),
            _rule(
                "AMAZON.RepeatIntent", "transport", "repeat", 1200, r"(?:repeat|replay|play again)"
            ),
            _rule(
                "AMAZON.StartOverIntent",
                "transport",
                "start_over",
                1200,
                r"(?:start over|restart|from the beginning)",
            ),
            _rule(
                "RewindIntent", "transport", "rewind", 1200, r"(?:rewind|skip back|go back a bit)"
            ),
            _rule(
                "FastForwardIntent",
                "transport",
                "fast_forward",
                1200,
                r"(?:fast forward|skip ahead|go forward)",
            ),
            _rule(
                "SetPlaybackSpeedIntent",
                "playback_control",
                "speed_normal",
                1190,
                r"(?:(?:set|change) (?:play ?back )?speed to |play at )?(?:normal|regular|reset)(?: speed)?",
                slots=(("speed", "normal"),),
            ),
            _rule(
                "SetPlaybackSpeedIntent",
                "playback_control",
                "speed_half",
                1190,
                r"(?:(?:set|change) (?:play ?back )?speed to |play at )?half(?: speed)?",
                slots=(("speed", "half"),),
            ),
            _rule(
                "SetPlaybackSpeedIntent",
                "playback_control",
                "speed_double",
                1190,
                r"(?:(?:set|change) (?:play ?back )?speed to |play at )?double(?: speed)?",
                slots=(("speed", "double"),),
            ),
            _rule(
                "IncreaseSpeedIntent",
                "playback_control",
                "speed_increase",
                1190,
                r"(?:speed up|speed it up|increase(?: the| playback)? speed|(?:play|go|make|speak)(?: it| this)? fast(?:er)?|faster)",
            ),
            _rule(
                "DecreaseSpeedIntent",
                "playback_control",
                "speed_decrease",
                1190,
                r"(?:slow down|slow it down|decrease(?: the| playback)? speed|reduce(?: the)? speed|(?:play|go|make|speak)(?: it| this)? slow(?:er)?|slower)",
            ),
            _rule(
                "SearchLocationIntent",
                "location_mutation",
                "location_with_value",
                1100,
                r"(?:set|change|update) my (?:location|town|city|area) to (?P<place>.+)",
                slot_name="searchQuery",
                capture_name="place",
                bypass_resolver=False,
            ),
            _rule(
                "SearchLocationIntent",
                "location_mutation",
                "moved_to",
                1100,
                r"i(?: ve| have)? moved to (?P<place>.+)",
                slot_name="searchQuery",
                capture_name="place",
                bypass_resolver=False,
            ),
            _rule(
                "SearchLocationIntent",
                "location_mutation",
                "live_in",
                1100,
                r"i now live in (?P<place>.+)",
                slot_name="searchQuery",
                capture_name="place",
                bypass_resolver=False,
            ),
            _rule(
                "SetLocationIntent",
                "location_mutation",
                "location_start",
                1090,
                r"(?:set|change|update) my (?:location|town|city|area)|set a new location|i (?:want|need) to (?:change|update) my location|i(?: ve| have)? moved|i moved|my location has changed|(?:change|update) where i (?:am|live)",
                bypass_resolver=False,
            ),
            _rule(
                "DisableNotificationsIntent",
                "notification",
                "notification_disable",
                1050,
                r"(?:disable|turn off|switch off|stop) (?:my )?(?:notifications?|alerts?|new content alerts)|stop sending (?:publication )?alerts|do not notify me(?: about new content)?|don t notify me(?: about new content)?",
            ),
            _rule(
                "EnableNotificationsIntent",
                "notification",
                "notification_enable",
                1040,
                r"(?:enable|turn on|switch on) (?:my )?(?:notifications?|alerts?|new content alerts)|(?:notify me|alert me) about new content|tell me when there is something new|let me know when followed sources publish|send me new publication alerts",
            ),
            _rule(
                "HearNotificationsIntent",
                "notification",
                "notification_inbox",
                1030,
                r"(?:hear|play|check|read) (?:for )?(?:my )?(?:updates|notifications)|what (?:are|notifications) do i have|do i have any (?:updates|notifications)|anything new (?:for me|from (?:who|people|sources) i follow)|what(?: is|s) new from (?:who|people|sources) i follow",
            ),
            _rule(
                "ReportCreatorIntent",
                "report",
                "report_creator",
                1000,
                r"(?:report|flag) (?:this|the) (?:creator|author|person|artist|narrator|producer)|i want to report the creator|this (?:creator|person) (?:is inappropriate|is offensive|shouldn t be on here)|flag this author",
            ),
            _rule(
                "ReportContentIntent",
                "report",
                "report_content",
                990,
                r"(?:report|flag) (?:this|the )?(?:content|recording|audio|safety issue|harmful content|offensive content)|(?:this|the content) (?:is inappropriate|is offensive|is not appropriate|is harmful|is dangerous|is problematic|needs reporting|shouldn t be here)|i want to (?:report|flag) this|send this for safety review|mark this as inappropriate",
            ),
            _rule(
                "RateContentIntent",
                "feedback",
                "rating",
                980,
                r"(?:rate|score|review) (?:this|the|what i m listening to)(?: (?:content|recording|current content|current recording))?|(?:give|leave)(?: my)? feedback(?: on this (?:content|recording))?|feedback on this (?:content|recording)|tell you what i think",
            ),
            _rule(
                "SkipFeedbackIntent",
                "feedback",
                "skip_feedback",
                970,
                r"(?:skip(?: (?:this )?(?:feedback|question|rating)| rating this)?|never mind|ignore that|don t bother|i don t want to rate|don t rate (?:it|this)|no comment|pass|i d rather not say|whatever|doesn t matter|not bothered|can t be bothered|carry on|just play the next one)",
            ),
            _rule(
                "UnfollowCreatorIntent",
                "social",
                "unfollow",
                960,
                r"(?:unfollow(?: this creator| them)?|unsubscribe(?: from (?:this creator|them))?|stop following(?: this creator)?|remove (?:this creator|them|from following)|drop this creator|i m done with this creator|take this creator off my list)",
            ),
            _rule(
                "FollowCreatorIntent",
                "social",
                "follow",
                950,
                r"(?:follow(?: this (?:creator|person|author|narrator|artist|voice))?|follow them|subscribe(?: to this creator)?|i want to follow this creator|add (?:this creator|them) to my (?:list|favourites|followed list)|keep me updated on this creator|save (?:this creator|them)|remember this creator|favourite this creator|bookmark this creator|keep this creator|more from this person)",
            ),
            _rule(
                "WhoIsCreatorIntent",
                "social",
                "creator_identity",
                940,
                r"(?:who (?:is this by|s this by|was this made by|made this(?: recording)?|created this|is the (?:creator|author)|recorded this|is speaking|is the narrator|published this|is this person|am i listening to|is talking|wrote this|produced this|s the artist|uploaded this|is behind this|s responsible for this)|who(?:se voice is this|s this)|tell me (?:who this is|about the (?:creator|author))|what creator is this|what s the name of the creator|give me (?:the credits|creator info)|(?:credit|credits|name of the creator))",
            ),
            _rule(
                "WhatsThisAboutIntent",
                "content_detail",
                "content_about",
                930,
                r"(?:what(?: s| is) (?:this|it|this content|this recording|this story)(?: all)? about|tell me about this (?:recording|content)|tell me what this is about|describe this recording)",
            ),
            _rule(
                "WhatsTrendingIntent",
                "trending",
                "trending",
                900,
                r"\b(?:trending|trend|popular|most popular|top (?:content|picks?|things)|what(?: s| is) hot|people listening to|everyone listening to)\b",
                search=True,
            ),
            _rule(
                "PlayRecommendationIntent",
                "recommendation",
                "recommendation",
                890,
                r"\b(?:recommend(?:ation)?s?|recommended|suggest|surprise me|what (?:do|would) you recommend(?:ed)?|what should i (?:listen to|hear)|what(?: s| is) good|find me something good|pick something for me|something you recommend|hit me with something|discover something new|curate something)\b",
                search=True,
            ),
            _rule(
                "SetUpAccountIntent",
                "account",
                "account_setup",
                880,
                r"(?:set ?up(?: my)? account|create (?:my |my listener )?account|finish (?:my )?account setup|personalise my account|sign me up|setup my profile|create my profile|finish setup|complete account setup|manage my account)",
            ),
            _rule(
                "PlayLocalIntent",
                "local_discovery",
                "local_content",
                870,
                r"\b(?:local (?:content|community|recordings?|audio)|(?:my )?local community|near (?:me|here)|nearby|around (?:me|here)|from my (?:city|town|area)|my (?:city|town|area))\b",
                search=True,
                bypass_resolver=False,
            ),
            _rule(
                "PlayLocalIntent",
                "local_discovery",
                "local_place",
                870,
                r"(?:play|find|show)(?: me)? (?:content|something|audio|recordings?) in .+",
                bypass_resolver=False,
            ),
        ),
        key=lambda rule: rule.priority,
        reverse=True,
    )
)

ROUTE_BYPASS_INTENTS = frozenset(
    rule.intent_name for rule in INTENT_ROUTE_RULES if rule.bypass_resolver
)

INTERRUPT_ROUTE_INTENTS = frozenset(
    rule.intent_name
    for rule in INTENT_ROUTE_RULES
    if rule.family in {"transport", "playback_control", "feedback", "report"}
)
