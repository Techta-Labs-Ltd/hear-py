# Alexa Search, Availability, Playback, and Feedback Audit

## Audit result

These were real design and coverage problems rather than one isolated bug. The corrective implementation described in this report was completed on 7 September 2026.

### Implementation status

- Search and availability responses now use the typed speech contract in this report.
- Playback introductions no longer promote `short_description` into a spoken title.
- Playback queues retain the exact organisation, creator, publication, topic, or location discovery context.
- Explicit mid-session feedback resumes the interrupted recording; return-time feedback asks whether to continue the exact previous discovery context.
- Raw positive, neutral, negative, and skip feedback phrases are normalized before dispatch.
- Bare `AMAZON.SkipIntent` dismisses an active feedback question instead of advancing playback.
- Generic source requests use the static no-ID `HEAR_SOURCE_KIND` slot and then elicit a domain-specific name.
- Unknown source names captured during an active organisation, creator, or publication dialog still go to the resolver.
- The generated slot validator covers all four domain slots and enforces domain ownership and approved canonical collisions.
- The cleaned imports contain 5,429 locations, 286 organisations, 14 creators, and 4,562 topics. The 276 organisation accounts copied into `HEAR_CREATOR` and the two generic talking-newspaper topics were removed.

Verification completed with 692 passing tests, valid interaction-model JSON, successful byte-code compilation, clean Ruff checks, and a strict architecture audit with 0 errors and 0 warnings.

The remaining acceptance work is external: build the revised Alexa model, run the utterance profiler, upload the generated slot imports, and verify the critical utterances on the physical Echo Dot. Live queue incidents still require the matching Alexa and backend logs for the affected `queueId`.

## 1. Search and availability speech

The sentence:

> I found content near you from York Talking News.

is hard-coded in `src/alexa/availability_speech.py`. Tests currently require this unwanted wording in `tests/test_availability_flow.py`.

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

Candidate objects already contain a `type`, so the speech layer can distinguish organisations, creators, and mixed results. However, `AvailabilityData.source_candidates()` currently combines both lists and de-duplicates them only by name. An organisation and creator with the same name can therefore be collapsed incorrectly.

### Required correction

- Generate the opening from the candidate types actually returned.
- Include the requested location when one exists.
- Use the listener’s saved location only when the request did not specify another location.
- Speak the exact resolved organisation, creator, or publication name.
- Do not describe every result merely as a generic “source”.
- Do not introduce source searches using an individual recording title or description.

## 2. Feedback requires two separate workflows

The application currently has one partial distinction: an explicit `RateContentIntent` sets `requested=true`. That path pauses and resumes the current recording. Automatic feedback presented after the listener returns to the skill does not retain enough information about the original search.

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

Currently, the queue mostly stores an intent identifier and search filters. The pending feedback record does not reliably retain the exact human-facing discovery label. The feedback response consequently falls back to a track title, creator credit, follow prompt, or generic idle prompt.

Following a creator should not replace the required continuation question. Queue continuation must be resolved first; a follow offer can happen separately.

## 3. Feedback recognition and the repeating prompt

The current interaction model contains `FeedbackResponseIntent` with a `HEAR_FEEDBACK` slot. The older `FeedbackEnjoyedIntent`, `FeedbackSomewhatIntent`, and `FeedbackNotEnjoyedIntent` handlers remain in the code and tests, but those intents are not present in the current interaction model.

The active feedback handler accepts only these exact normalized values:

- `enjoyed`
- `somewhat`
- `not enjoyed`

Alexa normally converts a configured synonym such as “I enjoyed it” to the canonical value `enjoyed`. However, a custom slot is training data rather than a strict enumeration. If Alexa returns an unmatched raw phrase, the application receives text such as `I enjoyed it`. The current exact dictionary lookup fails for that raw value and presents the feedback question again.

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

The feedback prompt tells listeners to say “skip”, but `SkipFeedbackIntent` deliberately does not include the bare word `skip`. Alexa can consequently route that word to a playback-next intent while leaving feedback pending.

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

## 5. `short_description` is currently being spoken

This is confirmed.

`ContentUtils._pick_curated_title()` chooses `shortDescription` as its first fallback. The normalizer can promote that value to `spokenTitle`, after which search and availability introductions speak it before playback.

There is also a test explicitly requiring an internal title such as `00000006` to be replaced with the short description “A weekly sport update from York”. That test now contradicts the required behaviour.

### Required policy

- Never use `short_description` or `shortDescription` in a playback introduction.
- Keep it for “What is this about?”, visual metadata, and description-specific features.
- For an organisation search, speak the exact organisation name.
- For a creator search, speak the exact creator name.
- For a publication search, speak the exact publication name.
- For a topic, category, tag, or general query, speak the requested search subject.
- Do not read an individual track description before playing audio.

If the backend title is an internal filename or identifier, do not replace it with the description for the introduction. Use the discovery context instead.

## 6. Generic fallback wording is duplicated

The phrase “play followed by a topic, or what’s trending” occurs across:

- `src/alexa/speech.py`
- `src/alexa/search_speech.py`
- `src/models/intent_dispatch.py`
- `src/models/decline.py`

It appears in welcome reprompts, generic errors, search no-match responses, and decline handling.

### Correct shared wording

> Please say the name of a talking newspaper, creator, publication, or city you would like to hear content from.

This shared wording should be used for generic fallback, no-input, error, idle-recovery, and no-match guidance.

Context-specific prompts should remain specific:

- “Which creator would you like to hear?”
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
- `HEAR_CREATOR`: actual individual creators, authors, readers, narrators, and contributors only.
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

`ContentFormat` already contains some newspaper synonyms, but it is attached to the general content intent. It does not reliably protect the organisation capture path.

### Intent ownership

There should be one primary intent owner for each carrier phrase:

| Carrier phrase | Owner |
| --- | --- |
| `play from …` | organisation flow |
| `play by …` | creator flow |
| `play publication …` | publication flow |
| `play …` | general topic/content flow |

The current model contains direct competition such as:

- `play from {searchQuery}`
- `play from {organizationQuery}`
- `play {searchQuery}`
- `play {topic}`
- `play {organizationQuery}`

Alexa does not provide a dependable manual priority between overlapping intents. The model should remove unnecessary duplicate carriers and use dialog state plus the resolver after Alexa selects the domain.

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
- “Play by David Beard.”
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
