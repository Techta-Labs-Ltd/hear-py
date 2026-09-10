# Carrierless discovery plan

## Required behavior

Hear must support both forms without changing their meaning:

```text
play Liverpool
Liverpool
```

The same applies to a talking newspaper, publication, creator, topic, tag, or
content title. After Hear asks what the listener wants, the listener must not
have to add `play` or `find` before the name.

## Behavior that must remain stable

- Existing carrier-based requests continue to use their current intents and
  slots, including the `AMAZON.SearchQuery` routes.
- Search confirmation and its `AMAZON.YesIntent` / `AMAZON.NoIntent` handling
  remain unchanged.
- Location onboarding, source capture, feedback, ambiguity selection, playback
  controls, cancellation, and other contextual dialogs keep ownership of their
  replies.
- The Hear resolver remains authoritative for deciding whether captured words
  mean a location, organization, publication, creator, topic, tag, or title.

## Cause of the failure

A top-level custom-slot-only sample such as `{topic}` does not reliably capture
an arbitrary bare reply. Alexa may select `AMAZON.FallbackIntent`, which has no
slot containing the spoken words. The Lambda and resolver therefore never see
`Liverpool`, and the skill repeats its discovery prompt.

`AMAZON.SearchQuery` handles unpredictable text when it has a carrier phrase,
but Alexa requires that slot type to appear with a carrier phrase. It cannot be
used as a top-level bare `{title}` utterance.

## Selected implementation

1. Keep every existing carrier-based intent and sample unchanged.
2. When Hear gives a generic idle discovery prompt, return a
   `Dialog.ElicitSlot` directive that starts `CarrierlessDiscoveryIntent` and
   asks Alexa to fill its `topic` slot.
3. Give that slot dialog-only answer patterns for both forms: `{topic}` and
   existing carrier forms such as `play {topic}`, `find {topic}`, and
   `play content about {topic}`. This lets a listener answer naturally without
   breaking a listener who still says `play`.
4. Forward either the canonical slot value or the unmatched spoken value to the
   existing resolver. The carrierless slot is transport only; it does not
   classify the phrase as a topic.
5. Let the resolver's result select the existing location, organization,
   publication, creator, topic/tag, or title behavior and confirmation.
6. Do not add the generic carrierless directive to search-confirmation or other
   active contextual prompts. Those dialogs retain their current Yes/No or
   domain-specific slot handling.

## Rejected model-only attempt

Removing competing top-level bare slot samples was tested first. The model built
successfully, but Alexa still selected fallback for `Liverpool`, `Dorking`, and
`Talking News Federation`. That candidate was restored without being committed
or pushed. A dialog elicitation is required because it biases Alexa specifically
for the answer to Hear's open discovery question.

## Acceptance matrix

| Input | Required outcome |
| --- | --- |
| `play Liverpool` | Existing route sends `Liverpool` to the resolver and gives location confirmation |
| `Liverpool` | Carrierless dialog sends `Liverpool` to the resolver and gives the same confirmation |
| `play content about Orion Meta Glasses` | Existing route reaches the resolver and gives topic/title confirmation |
| `Orion Meta Glasses` | Carrierless dialog reaches the resolver with the same bare words |
| `play from Talking News Federation` | Existing organization route remains operational |
| `Talking News Federation` | Carrierless dialog reaches the resolver and uses organization handling |
| `Premier League` | Carrierless dialog reaches the resolver and uses topic/tag handling |
| confirmation followed by `yes` | Existing confirmed-search execution |
| confirmation followed by `no` | Existing decline behavior |
| a different phrase during confirmation | Existing replacement/ambiguity behavior, not generic carrierless capture |

## Verification and rollback gate

Before keeping or pushing the change:

1. Run compile, lint, the strict architecture audit, focused interaction tests,
   and the complete test suite.
2. Build all four development interaction-model stages.
3. Profile the protected carrier utterances and confirm they still select their
   existing intents.
4. Deploy development and test fresh multi-turn sessions for bare and carrier
   inputs, confirmation Yes/No, onboarding, ambiguity, source capture, playback,
   and cancellation.
5. If a protected carrier route or contextual dialog regresses, immediately
   restore both the last working Lambda and interaction model.

## Alexa references

- https://developer.amazon.com/en-US/docs/alexa/custom-skills/slot-type-reference.html
- https://developer.amazon.com/en-US/docs/alexa/interaction-model-design/design-the-custom-intents-for-your-skill.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/define-the-dialog-to-collect-and-confirm-required-information.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/dialog-interface-reference.html
