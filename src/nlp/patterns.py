TRENDING_HINTS = {
    "what's trending", "whats trending", "what is trending", "what's popular",
    "what is popular", "what's hot", "what is hot", "trending", "popular",
    "what are people listening to", "what is everyone listening to", "top content",
    "show me trending", "show me what's trending", "read me the trending list",
    "what's trending right now", "what's on trend", "trending audio",
    "popular picks", "most popular right now",
}

LOCAL_HINTS = {
    "local", "nearby", "near me", "near here", "local content",
    "what's local", "whats local", "what is local", "local community",
    "community", "around me", "around here", "content near me",
    "local recordings", "nearby recordings", "local audio",
    "nearby audio", "what's happening near me", "my city", "my town",
    "from my city", "from my town", "my community", "from my community",
    "something from my community", "play community", "play community content",
    "what's happening locally", "whats happening locally", "locally",
}

FOLLOWING_HINTS = {
    "following", "followed", "from my followed creators", "from followed creators",
    "something from my followed creators", "from people i follow",
    "my followed creators", "followed creators", "i follow",
    "show me from my followed", "play from my followed",
}

BROWSE_HINTS = {
    "what's on", "whats on", "what's available", "whats available",
    "what have you got", "what's new", "whats new", "any new content",
    "what's been published", "what do you recommend", "recommend something",
    "any new episodes", "what's fresh", "whats fresh", "what dropped today",
    "let me hear what's new", "show me what you've got", "browse",
}

MORE_HINTS = {
    "show me more", "what are the next ones", "what are the next content found",
    "next ones", "more recordings", "more content", "what else did you find",
    "keep going", "what comes next",
}

FEEDBACK_ENJOYED_HINTS = {
    "enjoyed", "i enjoyed it", "yes i enjoyed it", "i liked it", "that was great",
    "loved it", "great", "good one", "brilliant", "amazing", "fantastic",
    "that was good", "really good", "excellent", "wonderful", "superb",
    "i loved that", "that was brilliant", "very good", "top notch", "smashing",
    "cracking", "well done", "that was lovely", "really enjoyed that",
}

FEEDBACK_SOMEWHAT_HINTS = {
    "somewhat", "it was okay", "kind of", "sort of", "not bad", "alright",
    "so so", "average", "not really", "it was alright", "it was fine",
    "could be better", "fair enough", "decent", "middling", "passable",
    "nothing special", "meh", "mid",
}

FEEDBACK_NOT_ENJOYED_HINTS = {
    "not enjoyed", "did not enjoy it", "did not like it", "bad", "not for me",
    "terrible", "change it", "not interested", "awful", "dreadful", "rubbish",
    "boring", "didn't enjoy it", "didn't like it", "not my cup of tea",
    "disliked it", "that was poor", "not good", "i hated that", "that was dull",
}

FEEDBACK_SKIP_HINTS = {
    "skip", "never mind", "no thanks", "ignore that", "skip feedback",
    "move on", "don't bother", "i don't want to rate", "no comment", "pass",
    "skip the rating", "carry on", "i'd rather not say", "just play the next one",
    "whatever", "doesn't matter", "skip it", "not bothered", "can't be bothered",
}

ALEXA_TO_NLP = {
    "PlayContentIntent": "general",
    "PlayByCreatorIntent": "creator",
    "PlayByOrganizationIntent": "organization",
    "WhatsTrendingIntent": "trending",
    "PlayRecommendationIntent": "trending",
    "PlayLocalIntent": "local",
    "BrowseContentIntent": "browse",
    "ShowMoreBrowseIntent": "show_more",
    "SetLocationIntent": "location_set",
    "TownCaptureIntent": "town_capture",
    "ClarifySelectionIntent": "general",
    "AMAZON.FallbackIntent": "general",
}

COMMAND_DENY = {
    "play", "find", "search", "show", "tell", "give", "get", "read", "hear",
    "listen", "start", "put", "me", "my", "i", "a", "an", "the", "some",
    "something", "anything", "content", "recording", "recordings", "track",
    "tracks", "audio", "podcast", "podcasts", "episode", "episodes",
    "latest", "newest", "recent", "most", "new", "from", "by", "near",
    "in", "on", "about", "of", "to", "for", "with", "please", "want",
    "would", "like", "you", "have", "do", "us",
    "what", "whats", "is", "are", "was", "were", "trending", "popular",
    "hot", "browse", "available", "recommend", "recommended", "everyone",
    "anyone", "people", "listening", "going", "happening", "around",
    "here", "today", "fresh", "now",
}

TOWN_CAPTURE_DENY = {"yes", "no", "stop", "cancel", "help", "skip", "quit"}
