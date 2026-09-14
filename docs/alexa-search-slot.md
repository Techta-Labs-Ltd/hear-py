# Alexa generated domain-slot contract

The Hear backend generates three separate custom Alexa slot types:

- `HEAR_LOCATION`
- `HEAR_ORGANIZATION`
- `HEAR_TOPIC`

`CarrierlessDiscoveryIntent` keeps its `HEAR_TOPIC` sample and generated
`HEAR_DISCOVERY` bridge. The build step fills that bridge with the canonical
values already present in the three domain catalogues. Approved aliases already
attached to the same canonical value in the base model are retained when the
full catalogues replace its seed values. The bridge also copies unambiguous
organisation and topic aliases. Location aliases remain in
`HEAR_LOCATION`, whose bare-value intent stays active alongside the bridge;
copying every location pronunciation into both slots would exceed Alexa's
interaction-model size limit. An alias shared by different canonical entities
is deliberately omitted from the bridge and left for the resolver to
disambiguate. The bridge does not invent or maintain a fifth vocabulary.

The general listening prompt elicits `OpenDiscoveryIntent.searchQuery`, an
`AMAZON.SearchQuery` slot. Existing custom-slot intents remain active and give
Alexa Hear-specific recognition context for known names. When Alexa does not
select one of those intents but can still recognize the reply as a query, the
open slot sends its raw text to the resolver. A unique, usable custom-slot match
supplies the canonical resolver input while the original captured text remains
separately available. A failed custom-slot resolution, ambiguous match, or
unusable canonical value sends the captured text instead. The resolver remains
responsible for deciding whether a bare reply is a location, organisation,
topic, tag, publication, title, or a directly spoken creator phrase.

The interaction model also contains the small, static `HEAR_SOURCE_KIND` slot.
It is not generated from catalogue data. Its canonical values are `talking
newspaper`, `publication`, and `creator`, with common spoken variants. It
routes a generic request into the correct discovery flow without sending a
generic phrase to the resolver. A generic creator request starts city capture.

`HEAR_CLARIFICATION` is not generated from the catalogue. Keep its stable
fallback values in the interaction model for `first`, `second`, `third`,
`publications`, and `tracks`. During an ambiguity response, the skill replaces
that slot's active session values with the currently spoken candidates through
`Dialog.UpdateDynamicEntities`.

Ordinal selection is deliberately reinforced in all three recognition layers.
The static slot and each dynamic candidate include safe forms such as `one`,
`1st`, `option one`, `choice 1`, and `number one` (and the equivalent second
and third forms). The backend applies the same normalization while an ambiguity
or availability choice is active, so replies such as `play first`, `pick option
two`, or `select choice 3` still choose the displayed item even if Alexa routes
the reply through another intent. Do not add broad unrelated sound-alikes: an
unknown phrase must cause a retry instead of silently selecting the wrong item.

These slots give Alexa domain-specific speech-recognition vocabulary. They do
not replace the Hear resolver or catalog. Every populated slot still travels
through the resolver, whether Alexa matched a generated value or returned raw
spoken text.

## Exact backend output

Generate this object. Slot values contain only `name.value` and optional
`name.synonyms`. Do not emit an `id` property.

```json
{
  "types": [
    {
      "name": "HEAR_LOCATION",
      "values": [
        {
          "name": {
            "value": "Herne Bay",
            "synonyms": [
              "arn bay",
              "earn bay",
              "Herne Bay area"
            ]
          }
        },
        {
          "name": {
            "value": "London"
          }
        }
      ]
    },
    {
      "name": "HEAR_ORGANIZATION",
      "values": [
        {
          "name": {
            "value": "Tynedale Talking Newspaper",
            "synonyms": [
              "Tynedale",
              "Tyndale",
              "Tyne Dale",
              "Tynedale Talking News"
            ]
          }
        }
      ]
    },
    {
      "name": "HEAR_TOPIC",
      "values": [
        {
          "name": {
            "value": "sport",
            "synonyms": [
              "sports",
              "sports news"
            ]
          }
        },
        {
          "name": {
            "value": "Premier League",
            "synonyms": [
              "English Premier League",
              "premiership",
              "E. P. L."
            ]
          }
        }
      ]
    }
  ]
}
```

Build the uploadable interaction model from the checked-in base model and all
three generated catalogues before uploading it to Alexa:

```bash
python scripts/build_alexa_interaction_model.py --output build/en-GB.json
```

Upload `build/en-GB.json`, not the seed-only `en-GB.json`. The builder replaces
the three matching objects in `interactionModel.languageModel.types`, writes a
compact model that stays within Alexa's size limit, and fails rather than
silently omitting one of the three domain slots.

For manual Alexa Console imports, the repository produces the three backend
domain files under `alexa-slot-imports/`:

- `HEAR_LOCATION.csv`
- `HEAR_ORGANIZATION.csv`
- `HEAR_TOPIC.csv`

Import each file through that slot type's **Bulk Edit** screen. The files do
not contain a header row. Each row uses `value,,synonym,...`; the deliberately
blank second column is the optional Alexa identifier, so these imports retain
the no-ID contract. Importing a file replaces the values currently displayed
for that slot type, after which the interaction model must be saved and built.

## What belongs in each slot

| Slot | Backend records |
| --- | --- |
| `HEAR_LOCATION` | Active towns, cities, localities, areas, and their observed spoken variants |
| `HEAR_ORGANIZATION` | Full backend organization names, plus distinctive spoken names and observed ASR variants |
| `HEAR_TOPIC` | Every active topic, category, subject, and searchable tag, including multi-word values |

Do not copy all records into every slot. Domain separation is what helps Alexa
prefer `London` as a location instead of a creator name. If the same phrase
exists in multiple domains, keep it only where users genuinely use it or rely
on the resolver to clarify the unavoidable ambiguity.

Cross-slot canonical collisions fail validation unless the phrase is listed in
`allowCrossSlotCollisions`. Synonym overlap is allowed
because carrier phrases and active dialog establish the domain, but duplicate
canonical values must be an explicit catalogue decision.

The repeatable cleanup policy is stored in
`config/alexa_slot_lexicon.json`. Run
`python scripts/apply_alexa_slot_lexicon.py alexa-slot-imports` after the
backend generates fresh CSV files and before importing them into Alexa.

## Intent-to-slot mapping

| Intent field | Slot type |
| --- | --- |
| `PlayLocalIntent.localQuery` | `HEAR_LOCATION` |
| `PlayLocalIntent.cityQuery` | `HEAR_LOCATION` |
| `TownCaptureIntent.townName` | `HEAR_LOCATION` |
| `SetLocationIntent` | no slot; explicit location-change command only |
| `SearchLocationIntent.searchQuery` | explicit location-change fallback |
| `PlayByOrganizationIntent.organizationQuery` | `HEAR_ORGANIZATION` |
| `SelectOrganizationIntent.organizationQuery` | `HEAR_ORGANIZATION` |
| `PlayPublicationIntent.publicationSourceQuery` | `HEAR_ORGANIZATION` |
| `SelectPublicationSourceIntent.publicationSourceQuery` | `HEAR_ORGANIZATION` |
| `SearchCreatorIntent.searchQuery` | `AMAZON.SearchQuery` |
| `SelectCreatorCityIntent.cityQuery` | `HEAR_LOCATION` |
| `ChooseSourceKindIntent.sourceKind` | static `HEAR_SOURCE_KIND` |
| Discovery `topic` and recommendation fields | `HEAR_TOPIC` |
| `CarrierlessDiscoveryIntent.topic` | `HEAR_TOPIC` |
| `CarrierlessDiscoveryIntent.discoveryQuery` | generated `HEAR_DISCOVERY` bridge |
| `OpenDiscoveryIntent.searchQuery` | `AMAZON.SearchQuery` open-query fallback |

Existing bare source and location intents retain their domain-specific slots.
`CarrierlessDiscoveryIntent` covers a bare topic or other phrase that Alexa
assigns to the generated bridge. `OpenDiscoveryIntent` captures a recognizable
bare phrase that Alexa does not assign to a typed intent while the general
prompt is active. Bare values captured while a town or source-name dialog is
active are interpreted by that active dialog before general discovery. The
intent-specific `AMAZON.SearchQuery` fallbacks and their carrier phrases remain
unchanged.

Direct creator phrases use `SearchCreatorIntent` and the general resolver. The
existing creator playback path continues only when resolution returns a
concrete creator ID. An unresolved creator phrase starts the city question and
never reaches raw catalogue search. Organization-owned publication requests use
`PlayPublicationIntent`, for example `play a publication from Tynedale Talking
Newspaper`.

## Generation rules

1. Emit exactly the three slot objects in the order shown above.
2. Emit only `name.value` and optional `name.synonyms`; never emit `id`.
3. Use the exact public/backend catalog name as the canonical `value`. This is
   the text Alexa sends to the resolver after a successful slot match.
4. For an organization whose public name ends in a generic phrase such as
   `Talking Newspaper`, add its distinctive spoken stem as a synonym. For
   example, the canonical value remains `Tynedale Talking Newspaper`, while
   `Tynedale`, `Tyndale`, and `Tyne Dale` are synonyms. Utterance templates
   must consume the complete organization slot. Do not place `talking news`,
   `talking newspaper`, or `talking magazine` after the slot placeholder,
   because Alexa can then truncate a full spoken name to only its first word.
5. Trim values, collapse repeated whitespace, and discard blank strings.
6. De-duplicate values and synonyms case-insensitively within each slot.
7. Do not assign one synonym to multiple canonical values in the same slot.
8. Keep every value and synonym at 140 characters or fewer.
9. Add observed speech variants and approved aliases, not arbitrary generated
   misspellings.
10. Exclude carrier words such as `play`, `from`, `by`, `near`, `creator`, and
   `organization` unless they are part of the entity's real public name.
11. Sort deterministically so identical backend data produces identical JSON.
12. Reject output that makes the complete interaction model exceed Alexa's
    size limit; retain margin for intents, samples, and prompts.
13. Treat `HEAR_TOPIC` as exhaustive at generation time. Compare its canonical
    values against every active topic, category, and searchable tag in the
    backend and fail generation when any are missing.
14. At the current catalogue size, apply the same completeness check to active
    locations, organizations, and creators. Never silently omit a record. If
    the complete model eventually exceeds Alexa's size limit, fail the job and
    report the counts and estimated model size so an explicit prioritisation
    policy can be chosen.

The backend source record should therefore expose, or derive, these fields:

```text
catalog_name       required canonical phrase emitted as name.value
spoken_stem        optional distinctive form without generic carrier words
approved_aliases   optional real alternative names
observed_asr_forms optional corrections learned from tested device transcripts
active             only active/searchable records are emitted
```

For `Tynedale Talking Newspaper`, the generator emits that complete catalog
name as `name.value`, then merges the `Tynedale` spoken stem with approved
aliases and observed forms such as `Tyndale` and `Tyne Dale`. It de-duplicates
them and emits no Alexa ID. Alexa supplies recognition vocabulary while the
resolver remains the authority for the actual record.

The schema in `schemas/alexa-search-slot.schema.json` validates this output and
rejects value-level IDs or other unexpected fields.

## Runtime behaviour

For every populated domain slot:

- On `ER_SUCCESS_MATCH`, the skill sends Alexa's canonical `name` to the Hear
  resolver.
- On no entity match, the skill sends Alexa's raw captured slot text to the
  Hear resolver.
- The resolver remains responsible for entity lookup, ambiguity, permissions,
  availability, and the final search filters.
- No Alexa entity ID is required or read for these three slots.

The normalized resolver result uses structured matches before free text:

1. If the resolver returns ambiguity candidates, the skill clears
   `residualQuery`, asks the listener to choose, and performs no content search.
2. Resolved creators, organizations, publications, categories, and tags become
   backend search filters. If any such filter is usable, the skill clears
   `residualQuery` and searches only with the structured filters.
3. A location with an explicit source role is preferred over an
   `unspecified` location.
4. When no source, category, tag, or stronger location was selected, the
   highest-confidence `unspecified` location at or above the resolver threshold
   becomes the location filter. An equal-confidence tie is not guessed.
5. `residualQuery` is used only when no usable entity and no ambiguity survives
   normalization. It is never retried after a structured search returns no
   content.

For example, if the resolver recognizes `Barking` at confidence 100 but also
returns the noisy residual text `and dagenham talking with repair`, the skill
sends an empty query with the structured Barking coordinates and country
filter. The residual words cannot override or broaden that entity match.

Location mutation is state-locked. `SetLocationIntent` has no slot and owns
only explicit commands such as `change my location`; it opens the location
capture state and asks for a city. `SearchLocationIntent` owns explicit
one-turn commands such as `change my location to Dorking`. `TownCaptureIntent`
owns bare or declarative city replies such as `Dorking` and `I live in
Dorking`, but those replies update the account only while onboarding or an
explicit location-change flow is active.

Outside location capture, a bare city that Alexa misclassifies as
`TownCaptureIntent` or `SetLocationIntent` is re-routed through general
discovery and cannot update the saved city. In the opposite direction, while
location capture is active, a city misclassified as a content or local-search
intent is re-routed to town capture and cannot start playback. The resolver
remains authoritative in both cases; conversation state decides whether the
request is a search or an account mutation.

Alexa's actual `AMAZON.FallbackIntent` request contains no slot and no raw
transcript for the skill endpoint to recover. It cannot be forwarded to the
resolver. During location capture, the skill therefore asks the listener to
repeat the city so `TownCaptureIntent` can preserve the words. Saying `skip` can arrive as
`AMAZON.NextIntent`, `AMAZON.SkipIntent`, or `SkipFeedbackIntent`; all three
bypass the resolver and complete the current optional onboarding step.

For ambiguity and availability replies:

- The skill stores the exact candidates it just spoke and keeps the dialog open.
- The response supplies those candidates to `HEAR_CLARIFICATION` dynamically,
  including distinguishing suffixes and ordinal synonyms.
- A reply such as `first`, `Dalesman`, `publications`, or `tracks` is matched
  against the stored current page before any new general search is allowed.
- The resolver remains authoritative for the original request; selecting a
  spoken candidate uses its stored resolution instead of starting an unrelated
  catalogue search.

Examples sent to the resolver:

```text
play from Tynedale Talking Newspaper
play sport from Tynedale Talking Newspaper
play a publication by Jane Smith
play near London
play sport near Herne Bay
```

The interaction model explicitly supports both complete commands and supported
follow-up turns. `Tynedale`, `Tynedale Talking Newspaper`, `play Tynedale Talking
Newspaper`, `play from Tynedale Talking Newspaper`, and `play sport from
Tynedale Talking Newspaper` all reach the same resolver. Bare organisation,
publication, and location names use their domain slots. Bare topics use
`CarrierlessDiscoveryIntent`, and recognizable uncatalogued phrases use
`OpenDiscoveryIntent` while the general prompt is active. Carrier-based forms
retain their existing intents.

When a generic creator request resolves through `ChooseSourceKindIntent`, the
skill activates `creator_location` and elicits
`SelectCreatorCityIntent.cityQuery`. That slot uses `HEAR_LOCATION`. The city is
sent to the resolver with location preference. A successful Alexa entity match
sends the canonical `HEAR_LOCATION` value; an entity no-match or absent
resolution sends the captured spoken value. Only a complete location returned
by the resolver is used transiently for creator-only availability. It is never
written to onboarding or the listener's saved location. The skill keeps no more
than the current three creator choices and reloads API pages for next and
previous navigation.

When the skill asks which talking newspaper or publication source the listener
wants, its `Dialog.ElicitSlot` response explicitly chains to
`SelectOrganizationIntent` or `SelectPublicationSourceIntent`. A custom slot no-match is valid when Alexa
selects the intent: its raw spoken value is still forwarded to the Hear
resolver. The skill also persists the active source-name dialog, so a bare
value arriving through any compatible slot intent is reinterpreted as the
expected source type instead of starting an unrelated general search. If Alexa
emits `AMAZON.FallbackIntent` without any slot text, there is no transcript for
the Lambda to recover, so the skill asks for the full name again without
requiring a carrier phrase.

If Alexa labels a name-only reply with the wrong bare-value intent while the
session is waiting for a town, organization, or publication source,
active dialog state takes precedence. The backend sends the captured words to
the expected route and only saves a city during the actual onboarding location
flow.

Keep the public catalogue name as the single canonical value for an
organisation. Add commonly spoken initialisms such as `TNF`, `T. N. F.`, and
`tee en eff` as approved synonyms of `Talking News Federation`. Alexa then
returns the public canonical name after a successful match, while an unmatched
raw form still goes to the resolver.

If a new value is absent from the generated slot, Alexa may still return it as
raw text through the custom slot. Alexa can also select the right source intent
without populating that custom slot. The interaction model therefore has
intent-specific `AMAZON.SearchQuery` fallbacks for arbitrary content, creator,
organization, publication, and location phrases. These fallbacks preserve the
carrier meaning (`play`, `play something by`, `play from`, `play publication from`, or
`my city is`) and send the complete captured phrase to the same Hear resolver.
They are not a second catalogue and do not bypass resolution.

When a free-text fallback produces a resolved primary source entity with an ID
and confidence at or above the resolver's established source threshold, that
structured resolver decision is authoritative. Short catalogue aliases such as
`tnf` therefore do not need to resemble the canonical display name. The skill
uses canonical-name comparison only for legacy or locally constructed results
that do not contain resolver confidence metadata. Unverified results are still
converted to a clear not-found response.

Absence from a generated custom slot can still reduce ASR accuracy, so publish
refreshed slot values when practical. Updating the Hear database or resolver
takes effect immediately for backend matching; changing Alexa's ASR vocabulary
takes effect only after the updated interaction model is uploaded and built for
the relevant skill stage. The open-query fallback does not turn arbitrary noise
or every possible character sequence into a valid Alexa utterance. If Alexa
emits `AMAZON.FallbackIntent` or rejects an utterance without a slot value,
Lambda has no transcript to send to the resolver.
