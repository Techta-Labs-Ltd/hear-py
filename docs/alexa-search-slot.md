# Alexa generated domain-slot contract

The Hear backend generates four separate custom Alexa slot types:

- `HEAR_LOCATION`
- `HEAR_ORGANIZATION`
- `HEAR_CREATOR`
- `HEAR_TOPIC`

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
      "name": "HEAR_CREATOR",
      "values": [
        {
          "name": {
            "value": "Jane Smith",
            "synonyms": [
              "Jane Smyth"
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

Replace the four matching objects in `interactionModel.languageModel.types` in
`en-GB.json` with the generated objects before uploading and building the
Alexa interaction model.

## What belongs in each slot

| Slot | Backend records |
| --- | --- |
| `HEAR_LOCATION` | Active towns, cities, localities, areas, and their observed spoken variants |
| `HEAR_ORGANIZATION` | Full backend organization names, plus distinctive spoken names and observed ASR variants |
| `HEAR_CREATOR` | Active creator, author, narrator, and contributor names |
| `HEAR_TOPIC` | Every active topic, category, subject, and searchable tag, including multi-word values |

Do not copy all records into every slot. Domain separation is what helps Alexa
prefer `London` as a location instead of a creator name. If the same phrase
exists in multiple domains, keep it only where users genuinely use it or rely
on the resolver to clarify the unavoidable ambiguity.

## Intent-to-slot mapping

| Intent field | Slot type |
| --- | --- |
| `PlayLocalIntent.localQuery` | `HEAR_LOCATION` |
| `PlayLocalIntent.cityQuery` | `HEAR_LOCATION` |
| `TownCaptureIntent.townName` | `HEAR_LOCATION` |
| `SetLocationIntent.location` | `HEAR_LOCATION` |
| `PlayByOrganizationIntent.organizationQuery` | `HEAR_ORGANIZATION` |
| `SelectOrganizationIntent.organizationQuery` | `HEAR_ORGANIZATION` |
| `PlayPublicationIntent.publicationSourceQuery` | `HEAR_ORGANIZATION` |
| `PlayByCreatorIntent.creatorQuery` | `HEAR_CREATOR` |
| `SelectCreatorIntent.creatorQuery` | `HEAR_CREATOR` |
| Discovery `topic` and recommendation fields | `HEAR_TOPIC` |

Creator-owned publication requests use `PlayByCreatorIntent`, for example
`play a publication by Jane Smith`. Organization-owned publication requests
use `PlayPublicationIntent`, for example `play a publication from Tynedale
Talking Newspaper`.

## Generation rules

1. Emit exactly the four slot objects in the order shown above.
2. Emit only `name.value` and optional `name.synonyms`; never emit `id`.
3. Use the exact public/backend catalog name as the canonical `value`. This is
   the text Alexa sends to the resolver after a successful slot match.
4. For an organization whose public name ends in a generic phrase such as
   `Talking Newspaper`, add its distinctive spoken stem as a synonym. For
   example, the canonical value remains `Tynedale Talking Newspaper`, while
   `Tynedale`, `Tyndale`, and `Tyne Dale` are synonyms. The intent grammar can
   supply `talking news` or `talking newspaper` around that stem.
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
- No Alexa entity ID is required or read for these four slots.

Examples sent to the resolver:

```text
play from Tynedale Talking Newspaper
play sport from Tynedale Talking Newspaper
play a publication by Jane Smith
play near London
play sport near Herne Bay
```

The interaction model explicitly supports both complete commands and name-only
turns. `Tynedale`, `Tyndale talking news`, `play from Tyndale talking news`, and
`play sport from Tyndale talking news` all populate the organization slot. A
bare creator name similarly populates `SelectCreatorIntent`. These selection
intents still go through the same Hear resolver as the longer play intents.

If Alexa labels a name-only reply as `TownCaptureIntent` while the session is
waiting for an organization or creator, active dialog state takes precedence.
The backend sends the captured words to the expected organization or creator
resolver route and does not save them as the listener's city. An actual
onboarding location question still owns a bare city response.

If a new value is absent from the generated slot, Alexa may still return it as
raw text and the resolver still receives it. Absence can reduce ASR accuracy,
so publish refreshed slot values when practical. Updating the Hear database or
resolver takes effect immediately for backend matching; changing Alexa's ASR
vocabulary takes effect only after the updated interaction model is uploaded
and built for the relevant skill stage.
