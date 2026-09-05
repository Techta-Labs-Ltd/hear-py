# Alexa generated search slot contract

The Hear backend generates the values for one custom Alexa slot type named
`HEAR_SEARCH_QUERY`. The slot is an ASR vocabulary hint. It is not the Hear
catalog, does not authorize a result, and does not replace the resolver.

## Exact backend output

Generate this object. Do not include an `id` property anywhere in a value:

```json
{
  "name": "HEAR_SEARCH_QUERY",
  "values": [
    {
      "name": {
        "value": "Tynedale Talking Newspaper",
        "synonyms": [
          "Tynedale Talking News",
          "Tynedale Talking News Paper"
        ]
      }
    },
    {
      "name": {
        "value": "Jane Smith",
        "synonyms": [
          "Jane Smyth"
        ]
      }
    },
    {
      "name": {
        "value": "Herne Bay",
        "synonyms": [
          "Herne Bay area"
        ]
      }
    },
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
```

Replace the `values` array of `HEAR_SEARCH_QUERY` in `en-GB.json` with the
generated array before uploading/building the Alexa interaction model.

## Records to include

Create one combined, de-duplicated vocabulary from active and searchable:

- organization and talking-newspaper names;
- creator names;
- publication titles and source names that users commonly request;
- supported town, city, locality, and area names;
- approved topics, categories, and tags.

The same slot type is deliberately used in different intent positions. The
utterance pattern supplies the meaning: `from` indicates an organization,
`by` indicates a creator, `in` or `near` indicates a location, and the other
slot in a two-part request is the topic. The backend resolver remains the final
authority for which entity and content the phrase represents.

## Generation rules

1. Emit only `name.value` and optional `name.synonyms`; never emit `id`.
2. Use the public spoken/display name as the canonical `value`.
3. Trim values, collapse repeated whitespace, and discard blank strings.
4. De-duplicate values and synonyms case-insensitively.
5. Do not assign the same synonym to multiple canonical values.
6. Keep every value and synonym at 140 characters or fewer.
7. Add only genuine spoken variants. Do not generate speculative misspellings.
8. Do not use generic carrier phrases such as `creator`, `organization`,
   `talking newspaper`, `play`, `from`, `near`, or `latest` as synonyms for an
   entity.
9. Sort deterministically so identical backend data produces identical JSON.
10. Reject output that makes the complete interaction model exceed Alexa's
    size limit; keep margin for intents and prompts.

## Runtime contract

For every populated discovery slot:

- If Alexa reports `ER_SUCCESS_MATCH`, the skill reads the canonical
  `value` and sends it to the resolver.
- If Alexa reports no match, the skill reads the raw spoken slot text and
  sends that to the resolver.
- No Alexa entity ID is required or read for this search slot.
- The resolver decides whether the phrase is an organization, creator,
  location, publication, topic, ambiguity, or no match.

Examples sent to the resolver include:

```text
play from Tynedale Talking Newspaper
play sport from Tynedale Talking Newspaper
play gardening by Jane Smith
play sport near Herne Bay
```

An unlisted new organization such as `North Moor Talking Newspaper` still
travels to the resolver as raw text. Being absent from the generated slot can
reduce Alexa's recognition accuracy, but it does not prevent backend lookup.
