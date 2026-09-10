# Carrierless discovery implementation

## Required behavior

Hear must support both forms without changing their meaning:

```text
play Liverpool
Liverpool
```

The same applies to a talking newspaper, publication, creator, topic, tag, or
content title. After Hear asks what the listener wants, the listener must not
have to add `play` or `find` before the name.

## Protected behavior

- Existing carrier requests keep their current intents, samples, and slot
  types, including `SearchContentIntent.searchQuery` as `AMAZON.SearchQuery`.
- Search confirmation and `AMAZON.YesIntent` / `AMAZON.NoIntent` remain
  unchanged.
- Onboarding, source capture, feedback, ambiguity selection, playback controls,
  cancellation, and other contextual dialogs retain ownership of their replies.
- The Hear resolver remains authoritative for classifying a captured phrase as
  a location, organization, publication, creator, topic, tag, or title.

## Cause

A top-level custom-slot-only utterance does not reliably capture an arbitrary
bare reply. Alexa can choose `AMAZON.FallbackIntent`, which contains none of the
spoken words, so the resolver never receives the phrase.

Alexa requires a carrier phrase around `AMAZON.SearchQuery` in top-level intent
samples. Amazon documents one important exception: the carrier may be omitted
from dialog slot samples. That exception fits the open question Hear asks after
launch and other idle discovery responses.

## Implementation

1. Keep the existing top-level `SearchContentIntent` samples unchanged:
   `play {searchQuery}`, `find {searchQuery}`, and `listen to {searchQuery}`.
2. Configure the same `searchQuery` slot as required in the Alexa dialog model.
   It remains one slot with one type: `AMAZON.SearchQuery`.
3. Add dialog-only slot samples for `{searchQuery}` and carrier forms such as
   `play {searchQuery}` and `play content about {searchQuery}`.
4. Add `Dialog.ElicitSlot` for `SearchContentIntent.searchQuery` only when Hear
   gives a generic idle discovery prompt.
5. Continue forwarding the captured value through the existing resolver. No
   location, organization, creator, publication, topic, tag, or title routing is
   duplicated in Alexa.
6. Do not add this generic directive to search-confirmation or contextual dialog
   responses; their current Yes/No and domain-specific capture stays intact.

## Rejected attempt

A first dialog candidate used `CarrierlessDiscoveryIntent.topic` with the
constrained `HEAR_TOPIC` slot. The model built, but a real development session
still rejected bare `Liverpool`. That candidate was immediately reverted in
both Git and the development Alexa model. The corrected implementation uses the
open-ended `AMAZON.SearchQuery` slot during dialog elicitation.

## Acceptance matrix

| Input | Required outcome |
| --- | --- |
| `play Liverpool` | Existing route reaches the resolver and gives Liverpool confirmation |
| `Liverpool` | Dialog slot reaches the resolver and gives the same confirmation |
| `play content about Orion Meta Glasses` | Existing route reaches topic/title handling |
| `Orion Meta Glasses` | Dialog slot reaches the resolver with the bare phrase |
| `play from Talking News Federation` | Existing organization route remains operational |
| `Talking News Federation` | Dialog slot reaches organization handling |
| `Premier League` | Dialog slot reaches topic/tag handling |
| confirmation then `yes` | Existing confirmed-search execution |
| confirmation then `no` | Existing decline behavior |
| a different phrase during confirmation | Existing replacement/ambiguity behavior |

## Verification and rollback gate

The change is kept only if all of the following pass:

1. JSON validation, compile, lint, strict architecture audit, focused tests, and
   the complete test suite.
2. All four Alexa development interaction-model build stages.
3. Alexa profiling for protected carrier utterances.
4. Fresh multi-turn development sessions for bare and carrier inputs, Yes/No,
   onboarding, ambiguity, source capture, playback, and cancellation.

If a protected carrier route or contextual dialog regresses, restore both the
last working Lambda and interaction model before continuing.

## Alexa references

- https://developer.amazon.com/en-US/docs/alexa/custom-skills/slot-type-reference.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/define-the-dialog-to-collect-and-confirm-required-information.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/dialog-interface-reference.html
