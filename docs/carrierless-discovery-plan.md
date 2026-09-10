# Carrierless discovery implementation

## Goal

After Hear asks what the listener wants, both of these must work identically:

```text
play Liverpool
Liverpool
```

The same rule applies to locations, organizations, talking newspapers,
publications, creators, topics, tags, and content titles. The captured phrase is
sent to the existing resolver, which remains responsible for classification.

## Protected behavior

- The existing top-level `play`, `find`, and `listen to` SearchQuery samples are
  unchanged.
- `SearchContentIntent.searchQuery` remains one slot with one type:
  `AMAZON.SearchQuery`.
- Search confirmation and Yes/No handling are unchanged.
- Onboarding, source capture, feedback, ambiguity, playback, navigation, Help,
  cancellation, notifications, and reporting retain their existing intents.

## Alexa constraint and solution

Alexa requires a carrier phrase around `AMAZON.SearchQuery` in a top-level
intent sample. Amazon explicitly permits the carrier to be omitted in a dialog
slot sample.

Hear therefore starts a `Dialog.ElicitSlot` for the existing
`SearchContentIntent.searchQuery` only when it gives a generic idle discovery
prompt. The dialog slot accepts a bare `{searchQuery}` as well as the existing
carrier forms. Alexa then sends both matched and unmatched text to the Lambda,
and the existing resolver classifies it.

An open-ended SearchQuery dialog can also capture a phrase such as `help` or
`what's trending` before Alexa switches intents. To preserve all established
commands, the captured phrase is first matched against the skill's existing
interaction-model samples. If an existing sample matches, its original intent
and slots are restored. If no sample matches, the phrase is left untouched and
sent to the resolver. This is not a discovery lexicon and does not predict user
names; it reuses the commands already declared in `en-GB.json`.

The generic capture directive is never attached to a search-confirmation or an
active contextual prompt, so Yes/No and contextual slot ownership stay intact.

## Acceptance matrix

| Input | Expected result |
| --- | --- |
| `Liverpool` | Resolver receives `Liverpool`; location confirmation |
| `play Liverpool` | Existing search behavior and the same confirmation |
| `Orion Meta Glasses` | Resolver receives the unmatched bare phrase |
| `play content about Orion Meta Glasses` | Existing carrier behavior |
| `Talking News Federation` | Resolver selects organization handling |
| `Premier League` | Resolver selects topic/tag handling |
| `help` | Existing Help intent |
| `what's trending` | Existing Trending intent |
| `play from a creator` | Existing source-kind capture |
| `set my location to Bristol` | Existing location-setting intent |
| confirmation then `yes` or `no` | Existing confirmation behavior |
| confirmation then `play Sevenoaks` | Existing replacement behavior |
| playback/navigation/cancel commands | Existing intent behavior |

## Rollback gate

Keep the change only if JSON validation, compile, lint, strict architecture
audit, the full test suite, all four Alexa model build stages, protected carrier
profiling, and the live multi-turn CLI matrix pass. If any protected interaction
regresses, restore both the Lambda and interaction model before continuing.

## Alexa references

- https://developer.amazon.com/en-US/docs/alexa/custom-skills/slot-type-reference.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/define-the-dialog-to-collect-and-confirm-required-information.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/dialog-interface-reference.html
