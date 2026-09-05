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
              "Tynedale Talking News",
              "Tynedale Talking News Paper"
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
| `HEAR_ORGANIZATION` | Active organizations, talking newspapers, and organization-owned publication/source names |
| `HEAR_CREATOR` | Active creator, author, narrator, and contributor names |
| `HEAR_TOPIC` | Approved topics, categories, subjects, and searchable tags |

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
| `PlayPublicationIntent.publicationSourceQuery` | `HEAR_ORGANIZATION` |
| `PlayByCreatorIntent.creatorQuery` | `HEAR_CREATOR` |
| Discovery `topic` and recommendation fields | `HEAR_TOPIC` |

Creator-owned publication requests use `PlayByCreatorIntent`, for example
`play a publication by Jane Smith`. Organization-owned publication requests
use `PlayPublicationIntent`, for example `play a publication from Tynedale
Talking Newspaper`.

## Generation rules

1. Emit exactly the four slot objects in the order shown above.
2. Emit only `name.value` and optional `name.synonyms`; never emit `id`.
3. Use the public spoken/display name as the canonical `value`.
4. Trim values, collapse repeated whitespace, and discard blank strings.
5. De-duplicate values and synonyms case-insensitively within each slot.
6. Do not assign one synonym to multiple canonical values in the same slot.
7. Keep every value and synonym at 140 characters or fewer.
8. Add observed speech variants and approved aliases, not arbitrary generated
   misspellings.
9. Exclude carrier words such as `play`, `from`, `by`, `near`, `creator`, and
   `organization` unless they are part of the entity's real public name.
10. Sort deterministically so identical backend data produces identical JSON.
11. Reject output that makes the complete interaction model exceed Alexa's
    size limit; retain margin for intents, samples, and prompts.

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

If a new value is absent from the generated slot, Alexa may still return it as
raw text and the resolver still receives it. Absence can reduce ASR accuracy,
so publish refreshed slot values when practical. Updating the Hear database or
resolver takes effect immediately for backend matching; changing Alexa's ASR
vocabulary takes effect only after the updated interaction model is uploaded
and built for the relevant skill stage.
