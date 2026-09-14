# Alexa Search, Availability, Playback, and Feedback Audit

## Audit result

These were real design and coverage problems rather than one isolated bug. The corrective implementation described in this report was completed on 7 September 2026.

### Implementation status

- Search and availability responses now use the typed speech contract in this report.
- Playback introductions no longer promote `short_description` into a spoken title.
- Playback queues retain the exact organisation, creator, publication, topic, or location discovery context.
- Explicit mid-session feedback resumes the interrupted recording; return-time feedback asks whether to continue the exact previous discovery context.
- Raw positive, neutral, negative, and skip feedback phrases are normalized before dispatch.
- Alexa's `AMAZON.SkipIntent` and `AMAZON.NextIntent` interpretations of “skip” dismiss an active feedback or report question instead of advancing playback.
- Generic source requests use the static no-ID `HEAR_SOURCE_KIND` slot. Creator requests elicit a city; organisation and publication requests retain their existing name flows.
- Unknown creator names never reach raw catalogue search. Direct creator phrases continue only when the resolver supplies a concrete creator ID.
- The generated slot validator covers the three active domain slots and enforces domain ownership and approved canonical collisions.
- The obsolete creator-name slot import was removed. Locations, organisations, and topics remain generated domains.

Verification completed with 715 passing tests, valid interaction-model JSON, successful byte-code compilation, clean Ruff checks, and a strict architecture audit with 0 errors and 0 warnings.

### Final requirement re-verification — 7 September 2026

| Requirement | Verified result |
| --- | --- |
| Typed availability speech | One and multiple results use the returned organisation and creator types. A known requested or saved city is spoken by name. Coordinate-only results make no proximity claim. |
| Mid-session feedback | The interrupted recording resumes from its saved offset. |
| Return-time feedback | Hear asks about the exact organisation, creator, publication, topic, or location context. Selected publication names survive queueing and relaunch; legacy placeholder titles are rejected rather than spoken. |
| Feedback recognition | Canonical and raw positive, neutral, negative, and dismissal phrases are normalized before routing. Both Alexa skip interpretations are intercepted while feedback is active. |
| Queue continuation | `PlaybackNearlyFinished` produces an `ENQUEUE` directive with the matching previous token, including lazy page loading and subsequent queue items. |
| Playback introductions | `short_description` remains metadata only. Unusable track titles do not become spoken titles, discovery context supplies the introduction, and choosing a publication speaks that publication rather than its parent organisation. |
| Relaunch resume prompt | Topic searches retain “content on {topic}” and add the valid organisation or creator behind the current recording. The recording description is never substituted for that context. |
| Generic recovery speech | Fallback, unmatched-intent, idle-recovery, resolver-unavailable, decline, and no-match paths use the shared listening prompt. |
| Interaction model and resolver | Domain slots remain separate, generic source-kind requests are handled locally, known and raw names reach the resolver, and ambiguity stays typed. |

No production speech path contains the removed generic proximity phrase, the removed fabricated recording title, or the old “play followed by a topic” guidance.

The remaining acceptance work is external: build the revised Alexa model, run the utterance profiler, upload the generated slot imports, and verify the critical utterances on the physical Echo Dot. Live queue incidents still require the matching Alexa and backend logs for the affected `queueId`.

## Live development verification — 7 September 2026

The deployed development skill was exercised through Alexa after the first corrective release. The results below distinguish application defects from catalogue and Alexa ASR limitations.

### Verified working

| Utterance | Alexa route | Verified response or outcome |
| --- | --- | --- |
| “Play from a talking newspaper” | `ChooseSourceKindIntent` | “Which talking newspaper would you like?” |
| “Tynedale Talking News” after that prompt | `SelectOrganizationIntent` | Resolver canonicalised the name and Hear asked, “Did you want me to play content from Tynedale Talking Newspaper?” |
| “Play from a creator” | `ChooseSourceKindIntent` | “Which city would you like me to find creators in?” |
| “Play something on Premier League” | `PlayContentIntent` | The topic survived confirmation and playback began with “Playing content on Premier League.” |
| “Play last week sport update” | `SearchContentIntent` | The resolver date range was spoken as “published from 30 August to 5 September 2026.” |
| “Play yesterday’s sport” | `PlayContentIntent` | The resolved calendar date was retained in the confirmation. |
| “What’s trending in sport?” | `WhatsTrendingIntent` | Trending semantics and the sport topic were retained. |
| “Recommend sport” | `PlayRecommendationIntent` | Recommendation/trending semantics and the sport topic were retained. |
| “Play the latest publication from Talking News Federation” | `PlayPublicationIntent` | Publication source and latest sort were retained. |
| Explicit “rate this content”, followed by “I enjoyed it” | Feedback flow | The interrupted recording resumed at its saved position. |

### Newly detected defects and corrections

| Defect | Root cause | Required behaviour | Correction |
| --- | --- | --- | --- |
| Saying “skip” during feedback played the next recording. | The Echo mapped the spoken word to `AMAZON.NextIntent`; the feedback gate handled only `AMAZON.SkipIntent`. | During an active feedback or report question, both Alexa interpretations must mean “dismiss this question”. For an explicitly requested rating, resume the same recording. | The contextual feedback gate now accepts both intents, before the ordinary playback-next controller. |
| “Play something from London” was confirmed correctly, but the availability response used generic proximity wording. | `ResolutionBuilder` discarded the explicit-location marker before the yes-confirmation request. | “I found Test TN User near London. Would you like to listen?” | Pending resolutions retain `requestedLocation`, and availability now speaks either the explicitly requested city or the listener’s saved city. |
| “Play a publication” asked for a publication, creator, or organisation. | The generic publication prompt reused broad source wording. | “Which publication would you like?” Reprompt: “Please say the publication name.” | The publication dialog now uses one shared, publication-specific speech constant. |
| A conflicting Dorking/Orkney resolver combination produced “publication from … from …”. | The confirmation layer preferred the raw publication query and appended an untrusted residual beside a canonical publication. | When a structured publication is accepted, speak only its canonical name unless a separate trusted category or tag is present. Example: “Did you want me to play Orkney Talking Magazine?” | Canonical `publicationName` now takes priority. Conflicting or duplicated raw source words are removed from the spoken subject. |

### External or catalogue findings

- After Tynedale was resolved and confirmed, the content API returned no playable content. The correct response is: “I couldn’t find anything for content from Tynedale Talking Newspaper right now. What would you like to try instead?” This is an availability/catalogue result, not a slot-routing failure.
- A bare unknown name such as “favor” after a creator prompt arrived as `AMAZON.FallbackIntent` with no slot text. Hear cannot send words to the resolver when Alexa supplies no transcript. Saying “play something by favor” does provide `searchQuery` and reaches the resolver. Uploading the full generated creator slot improves recognition for known creators but cannot make custom slots a strict or unlimited vocabulary.
- If the resolver confidently returns the wrong canonical entity, the speech layer now prevents duplicated or mixed wording but cannot invent the intended entity. That false match must be corrected in the resolver taxonomy, aliases, confidence policy, or generated Alexa slot lexicon.
- The deployed development model contained only small sample sets, not the complete generated imports. Physical-device acceptance requires uploading all four generated domain slots and rebuilding the development model.
- Console and phone success does not prove Echo Dot far-field recognition. The Echo Dot remains the acceptance device for names, acronyms, older voices, pace, and room noise.

### Speech rules confirmed by the live run

- A named organisation, creator, or publication is spoken using its canonical resolver name.
- A general subject is introduced as “Playing content on {subject}.”
- A known place is always repeated as “near {city}”, whether it came from the request or the listener’s saved location. If only coordinates are available, proximity wording is omitted.
- A prompt asks only for the missing domain: talking newspaper, creator, publication, or city.
- Resolver residual words never produce duplicated constructions such as “from {source} from {other source}”.
- `short_description` is never used as the pre-playback introduction.

## 1. Search and availability speech

Before correction, availability used generic proximity wording and could combine it with a source name. That wording was removed. A known requested or saved city is now spoken explicitly, and no proximity claim is made when only coordinates are available.

### Required speech contract

| Result | Required speech |
| --- | --- |
| One organisation | “I found York Talking News near York. Would you like to listen?” |
| One creator | “I found David Beard near York. Would you like to listen?” |
| One publication | “I found The Weekly Edition. Would you like to listen?” |
| Organisations only | “Here are the talking newspapers closest to York.” |
| Creators only | “Here are the creators closest to York.” |
| Organisations and creators | “Here are the talking newspapers and creators closest to York.” |
| General topic | “Playing content on sport.” |
| General query | “Playing content on Orion Meta Glasses.” |
| Organisation search | “Playing York Talking News.” |
| Creator search | “Playing David Beard.” |
| Publication search | “Playing The Weekly Edition.” |

“Closest to” is grammatically correct here, rather than “closer to”.

Candidate objects contain a `type`, so the speech layer distinguishes organisations, creators, and mixed results. `AvailabilityData.source_candidates()` now de-duplicates by both type and normalized name, so an organisation and creator with the same name remain distinct.

### Required correction

- Generate the opening from the candidate types actually returned.
- Include the requested location when one exists.
- Use the listener’s saved location only when the request did not specify another location.
- Speak the exact resolved organisation, creator, or publication name.
- Do not describe every result merely as a generic “source”.
- Do not introduce source searches using an individual recording title or description.

## 2. Feedback uses two separate workflows

Before correction, the application had only a partial distinction: an explicit `RateContentIntent` set `requested=true`, while automatic feedback presented after the listener returned did not retain enough information about the original search. Both paths now retain and use the required state.

### Explicit mid-session rating

1. Pause the current recording.
2. Collect the feedback.
3. If the recording was interrupted, resume the same recording from its saved offset.
4. If the recording had already completed, play the next queued recording.

### Feedback presented when returning to Hear

1. Present feedback for the completed recording or publication.
2. Record the answer.
3. Do not immediately start unrelated content.
4. Ask whether the listener wants to continue the exact previous discovery context.
5. Use the exact organisation, creator, publication, or topic name.
6. If the listener says yes, play the next queued recording.
7. If the listener says no, clear that continuation and ask for a new request.

Example:

> Thanks for the feedback. Would you like to continue listening to York Talking News?

### State that must be retained

The playback queue or associated discovery state needs to retain:

- `kind`: organisation, creator, publication, or topic
- `name`: exact human-facing name
- `queueId`
- current queue position
- next queue position
- original structured search payload
- whether feedback was requested during playback or presented after returning

The queue and pending feedback record now retain the exact human-facing discovery context. Feedback uses that context instead of falling back to an unrelated track title, creator credit, follow prompt, or generic idle prompt.

Following a creator should not replace the required continuation question. Queue continuation must be resolved first; a follow offer can happen separately.

## 3. Feedback recognition and the resolved repeating-prompt defect

The interaction model contains `FeedbackResponseIntent` with a `HEAR_FEEDBACK` slot. Compatibility handlers exist for the older feedback intents, but active recognition and realistic request tests use `FeedbackResponseIntent`.

The active feedback handler dispatches these normalized values:

- `enjoyed`
- `somewhat`
- `not enjoyed`

Alexa normally converts a configured synonym such as “I enjoyed it” to the canonical value `enjoyed`. However, a custom slot is training data rather than a strict enumeration. The application now normalizes both canonical matches and unmatched raw phrases before dispatch instead of repeating the feedback question.

Amazon documents that custom-slot values outside the supplied list can still be returned and must be validated by the skill:

- [Create and Edit Custom Slot Types](https://developer.amazon.com/en-GB/docs/alexa/custom-skills/create-and-edit-custom-slot-types.html)

### Required correction

- Keep the canonical `HEAR_FEEDBACK` values.
- Expand the approved synonyms using actual device transcripts.
- Normalize both canonical matches and unmatched raw phrases in the feedback state.
- Interpret positive phrases as `enjoyed`.
- Interpret neutral phrases as `somewhat`.
- Interpret negative phrases as `not enjoyed`.
- Interpret feedback dismissal as `skipped`.
- Give active feedback state priority over general, yes/no, and playback routing.
- Test `FeedbackResponseIntent` using realistic Alexa request envelopes.
- Remove reliance on tests that fabricate interaction-model intents Alexa cannot emit.

Suggested positive phrases include:

- enjoyed
- I enjoyed it
- I enjoyed that
- yes, I enjoyed it
- I liked it
- I liked that
- loved it
- it was good
- that was great
- very good
- brilliant

Suggested neutral phrases include:

- it was okay
- it was alright
- not bad
- somewhat
- it was fine

Suggested negative phrases include:

- I did not enjoy it
- I didn’t enjoy that
- I didn’t like it
- not for me
- it was poor

### Skip mismatch

Alexa can route the bare word “skip” to a playback-next intent instead of `SkipFeedbackIntent`. The contextual feedback gate now intercepts both Alexa interpretations while feedback or a report question is active.

While feedback is active, `skip`, `never mind`, `pass`, and equivalent phrases must dismiss the feedback question. They must not advance playback through the ordinary transport-control path first.

## 4. Why the York search played only one recording

The normal queue implementation is structurally correct:

1. Search results initialize the queue.
2. Alexa sends `AudioPlayer.PlaybackNearlyFinished`.
3. Hear responds with an `AudioPlayer.Play` directive using `ENQUEUE`.
4. Alexa starts the second recording after the first ends.

Amazon requires the next stream to be supplied when `PlaybackNearlyFinished` is received. A `PlaybackFinished` response cannot start or enqueue another audio stream:

- [AudioPlayer Interface Reference](https://developer.amazon.com/en-US/docs/alexa/custom-skills/audioplayer-interface-reference.html)

The York failure must therefore be one of the following:

- The search API returned only one recording.
- Multiple results shared or lacked `contentId`, shrinking the queue.
- `total_pages` was absent or incorrect, preventing lazy loading.
- The second recording had no playable audio URL.
- The Echo did not deliver an accepted `PlaybackNearlyFinished` request.
- The next-content lookup failed or timed out.
- The `expectedPreviousToken` did not match the device’s active token, so Alexa ignored the enqueue request.

The application already logs this warning when playback finishes without a successful enqueue:

> Hear: queue could not advance because Alexa sent PlaybackFinished without an accepted PlaybackNearlyFinished enqueue

### Evidence required for one failed queue

The logs for one `queueId` should demonstrate all of the following:

1. Search response `returned` count and `total_hits`.
2. Initial `orderedContentIds` and current index.
3. `PlaybackStarted` for the first content token.
4. `PlaybackNearlyFinished` for that same token.
5. The next content lookup result.
6. The generated `ENQUEUE` directive and `expectedPreviousToken`.
7. `PlaybackStarted` for the second content token.
8. Any `PlaybackFailed`, timeout, or stalled-queue warning.

The unit tests prove that a synthetic three-item queue can enqueue its second and third recordings. They do not prove what the live York API returned or what the Echo sent.

The individual production incident could not be confirmed during this audit because the configured AWS CLI security token was invalid.

## 5. Resolved `short_description` playback-introduction defect

The original defect was confirmed and has been corrected.

Before correction, `ContentUtils._pick_curated_title()` chose `shortDescription` as its first fallback. The normalizer could promote that value to `spokenTitle`, after which search and availability introductions spoke it before playback.

The contradictory test that required an internal title such as `00000006` to be replaced with a short description was removed. Tests now require no spoken title for unusable metadata and verify that discovery context supplies the introduction.

### Required policy

- Never use `short_description` or `shortDescription` in a playback introduction.
- Never invent a generic title such as “a local recording.” “Local” describes the search context, not the recording itself.
- Keep it for “What is this about?”, visual metadata, and description-specific features.
- For an organisation search, speak the exact organisation name.
- For a creator search, speak the exact creator name.
- For a publication search, speak the exact publication name.
- For a topic, category, tag, or general query, speak the requested search subject.
- Do not read an individual track description before playing audio.

If the backend title is an internal filename or identifier, do not replace it with the description for the introduction. Use the discovery context instead.

The same rule applies after relaunching with unfinished playback. For a topic search, the resume question says “You were listening to content on {topic} from {organisation}” or, when there is no valid organisation, “by {creator}”. It never replaces the topic with `short_description`.

## 6. Resolved generic fallback wording duplication

Before correction, the phrase “play followed by a topic, or what’s trending” occurred across:

- `src/alexa/speech.py`
- `src/alexa/search_speech.py`
- `src/models/intent_dispatch.py`
- `src/models/decline.py`

It appears in welcome reprompts, generic errors, search no-match responses, and decline handling.

### Correct shared wording

> Please say the name of a talking newspaper, creator, publication, or city you would like to listen to.

This shared wording should be used for generic fallback, no-input, error, idle-recovery, and no-match guidance.

Context-specific prompts should remain specific:

- “Which city would you like me to find creators in?”
- “Which talking newspaper would you like?”
- “Which publication would you like?”
- “Which city should I use?”

The generic wording should not replace a specific question when the application already knows which value is missing.

## 7. Interaction-model and generated-slot conflicts

Before cleanup, the generated slot imports contained:

| Slot | Canonical values | Synonyms |
| --- | ---: | ---: |
| `HEAR_LOCATION` | 5,429 | 20,303 |
| `HEAR_ORGANIZATION` | 286 | 2,454 |
| `HEAR_CREATOR` | 290 | 3,064 |
| `HEAR_TOPIC` | 4,564 | 1,633 |

The audit found these problems in that pre-implementation snapshot:

- 276 of the 286 organisation canonical names also appear in `HEAR_CREATOR`.
- `HEAR_TOPIC` contains the generic values `Talking News` and `Talking Newspaper`.
- At least 101 topic values contain mechanically repeated or unusually combined wording under a basic repetition check.
- Organisation rows contain as many as 48 synonyms.
- Creator rows contain as many as 64 synonyms.
- The lexicon validator processes only `HEAR_LOCATION` and `HEAR_ORGANIZATION`.
- It does not validate `HEAR_CREATOR`, `HEAR_TOPIC`, or collisions across slot types.

This defeats the intended separation between organisations, creators, locations, and topics. In particular, `Talking News` and `Talking Newspaper` inside `HEAR_TOPIC` can push “play from a talking newspaper” toward a topic or general-search intent.

### Correct domain ownership

- `HEAR_LOCATION`: actual cities, towns, localities, and approved spoken variants.
- `HEAR_ORGANIZATION`: actual organisations and talking newspapers only.
- Creator names are not generated into a custom slot. Carrier-based creator phrases use `AMAZON.SearchQuery` and the resolver.
- `HEAR_TOPIC`: actual topics, categories, subjects, and searchable tags only.
- Do not place generic source-kind words in these entity slots.
- Do not copy organisations into the creator slot merely because an organisation owns a creator account in the backend.

### Generic source-kind slot

A small no-ID slot such as `HEAR_SOURCE_KIND` should identify what kind of source the listener wants:

| Canonical value | Synonyms |
| --- | --- |
| `talking newspaper` | talking news paper, talking news, audio newspaper, talking paper, local talking newspaper |
| `publication` | publication, edition, issue |
| `creator` | creator, author, narrator, reader, contributor |

Examples:

- “Play from a talking newspaper” identifies the source kind and asks for the organisation name.
- “Play a publication” identifies the source kind and starts the publication-selection flow.
- “Play from a creator” identifies the source kind and asks for the creator name.

The generic words `talking newspaper`, `publication`, and `creator` must not be sent to the resolver as though they were specific entity names.

Before cleanup, `ContentFormat` contained newspaper synonyms while being attached to the general content intent. Those values were removed because they did not protect the organisation capture path and competed with its domain slot.

### Intent ownership

There should be one primary intent owner for each carrier phrase:

| Carrier phrase | Owner |
| --- | --- |
| `play from …` | organisation flow |
| `play something by …` | creator flow |
| `play publication …` | publication flow |
| `play …` | general topic/content flow |

The pre-cleanup model contained direct competition such as:

- `play from {searchQuery}`
- `play from {organizationQuery}`
- `play {searchQuery}`
- `play {topic}`
- `play {organizationQuery}`

Alexa does not provide a dependable manual priority between overlapping intents. The cleaned model assigns each carrier phrase to a primary owner and uses dialog state plus the resolver after Alexa selects the domain.

Location routing follows the same ownership rule. `SetLocationIntent` owns only
explicit commands such as “change my location” and has no city slot.
`SearchLocationIntent` owns explicit one-turn mutations such as “change my
location to Swindon.” `TownCaptureIntent` may recognize “Swindon” or “I live in
Swindon,” but the backend treats it as an account update only during active
onboarding or location change. At the normal listening prompt, the same city is
sent through discovery without changing the saved location. While location
capture is active, a city misclassified as content search is routed back to
town capture and cannot begin playback.

Amazon recommends testing utterance conflicts and using the utterance profiler:

- [Best Practices for Sample Utterances and Custom Slot Type Values](https://developer.amazon.com/en-US/docs/alexa/custom-skills/best-practices-for-sample-utterances-and-custom-slot-type-values.html)

### Custom slots and the resolver

Custom slot values are recognition hints rather than a whitelist. An out-of-list value can still arrive as raw text. Therefore:

1. Alexa selects the appropriate domain intent.
2. A successful slot match provides the canonical slot value.
3. An unsuccessful slot match can still provide raw captured text.
4. Both forms go to the Hear resolver.
5. The resolver remains authoritative for the entity, confidence, ambiguity, availability, and filters.
6. No Alexa value IDs are required for this design.

When the skill elicits a missing slot, Alexa biases recognition using the slot’s configured utterances. The backend must still validate the answer because a manually issued `Dialog.ElicitSlot` does not apply Alexa dialog validation automatically:

- [Dialog Interface Reference](https://developer.amazon.com/en-US/docs/alexa/custom-skills/dialog-interface-reference.html)

### Acronyms

Initialisms should follow Alexa’s recommended spoken form. For example:

- canonical: `TNF`
- synonyms: `T. N. F.`, `tee en eff`

Lowercase `tnf` is less reliable because Alexa can interpret it as a word. The resolver can convert the canonical or raw alias to `Talking News Federation`; no Alexa entity ID is necessary.

## Required end-to-end workflow

1. Alexa identifies the domain from the carrier phrase or active dialog.
2. The appropriate domain slot captures a canonical value or raw text.
3. Generic source-kind requests are handled locally and elicit the missing name.
4. Specific names are sent to the resolver.
5. Resolver ambiguities become typed candidate choices.
6. Availability produces typed organisation, creator, or mixed-source speech.
7. Search creates a queue and persists the exact discovery context.
8. Playback introductions use the discovery context, not `short_description`.
9. `PlaybackNearlyFinished` enqueues the next recording.
10. Feedback preserves whether it was requested mid-session or presented after returning.
11. Return-time feedback asks whether to continue the exact previous organisation, creator, publication, or topic.

## Required test coverage

### Speech tests

- One nearby organisation.
- One nearby creator.
- Multiple organisations.
- Multiple creators.
- Mixed organisations and creators.
- One publication.
- General topic search.
- General free-text search.
- Assert that `short_description` is absent from every playback introduction.

### Interaction-model tests

- “Play from a talking newspaper.”
- “Play from a talking news paper.”
- “Play from a creator.”
- “Play a publication.”
- “Play from York Talking News.”
- “Play something by David Beard.”
- Known and unknown custom-slot values.
- `ER_SUCCESS_MATCH` and `ER_SUCCESS_NO_MATCH` request envelopes.
- Slot and sample-utterance conflict checks.

### Feedback tests

- Canonical `enjoyed` response.
- Raw `I enjoyed it` response without entity resolution.
- Neutral and negative raw responses.
- Bare `skip` during active feedback.
- Explicit mid-session rating resumes the interrupted recording.
- Completed-track feedback advances to the next queued recording.
- Return-time feedback asks to continue the exact organisation.
- Equivalent creator, publication, and topic continuation cases.

### Queue tests

- Search result with two or more recordings.
- Correct initial `orderedContentIds`.
- First `PlaybackStarted` event.
- First `PlaybackNearlyFinished` event.
- Correct `ENQUEUE` directive.
- Matching `expectedPreviousToken`.
- Second `PlaybackStarted` event.
- Lazy page loading.
- Unplayable next result.
- Backend timeout.
- Missing `PlaybackNearlyFinished` event.

### Device testing

Run the same critical utterances on:

- Alexa developer console
- Alexa mobile application
- Echo Dot using normal far-field speech
- Echo Dot using an older listener’s likely speaking pace and volume

The Echo Dot results must be treated as the acceptance result because console text entry does not exercise the same microphone and far-field ASR path.

## Recommended implementation order

1. Freeze the required speech contract.
2. Clean the generated slot files.
3. Validate every slot and cross-slot collision.
4. Add the small generic source-kind slot without IDs.
5. Remove competing duplicate intent utterances.
6. Persist exact discovery context with every playback queue.
7. Split mid-session and return-after-completion feedback flows.
8. Stop promoting `short_description` into spoken titles.
9. Add realistic Alexa request-envelope tests.
10. Add queue event-sequence integration tests.
11. Build the Alexa model and use the utterance profiler.
12. Test the complete flow on the physical Echo Dot.

## Architecture status

The strict architecture audit completed with:

```text
Architecture audit: 0 errors, 0 warnings
```

The problems described here concern behavioural contracts, generated slot quality, interaction-model conflicts, missing discovery context, and incomplete live integration coverage. They are not failures of the class/MVC structure.
