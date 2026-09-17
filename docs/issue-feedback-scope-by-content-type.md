# Issue: Enforce Feedback Scope by Content Identity

## Summary

Feedback scope must be determined by the content being played, not by the search route that found it.

- A publication should produce one publication-level feedback item for the publication as a whole.
- Every non-publication result should produce feedback for the individual track.
- Organization, creator, topic, category, and tag filters must never aggregate feedback across tracks.

## Severity

High. Incorrect scope can create misleading listener feedback, duplicate prompts, and incorrect backend analytics.

## Intended Behaviour

| Playback context | Feedback identity | Expected subject |
|---|---|---|
| Standalone track | `contentId` | `subjectType: content` |
| Organization filter, non-publication result | `contentId` | `subjectType: content` |
| Creator filter, non-publication result | `contentId` | `subjectType: content` |
| Topic search | `contentId` | `subjectType: content` |
| Category search | `contentId` | `subjectType: content` |
| Tag search | `contentId` | `subjectType: content` |
| Track belonging to a publication | `publicationId` | `subjectType: publication` |

The invariant is:

```text
publicationId present -> publication-level feedback
publicationId absent  -> individual-track feedback by contentId
```

`organizationId`, `creatorId`, category, tags, topic, and discovery source are descriptive context only. They must not determine feedback identity.

## Current Implementation

`FeedbackService.record_candidate()` branches on `state["publicationId"]`:

- With `publicationId`, it updates `publicationFeedbackProgress` and finalizes a publication candidate at the publication boundary.
- Without `publicationId`, it creates a content candidate whose `feedbackKey` is the content identity.

The relevant implementation is in:

- `src/alexa/feedback_service.py`
- `src/utils/content.py`
- `src/alexa/playback_state.py`
- `src/alexa/feedback_response.py`

Explicit mid-session feedback is requested by `RateContentIntent`. The skill pauses active playback, asks for feedback, and resumes the same track after the response.

## Risk

The implementation is correct only if normalized search results carry publication metadata accurately. A non-publication result that is incorrectly given a `publicationId` will be aggregated as publication feedback. A publication track that loses its `publicationId` will incorrectly receive individual track feedback.

Publication metadata can be incomplete when a publication is selected through availability and the follow-up track search returns incomplete fields. This can affect publication titles, track counts, completion detection, and feedback finalization.

## Proposed Fix

1. Centralize the scope rule in `ContentIdentity`.
2. Normalize playable results using `contentId` or `id`.
3. Preserve publication context when availability selects a publication:
   - `publicationId`
   - `publicationTitle`
   - publication membership
   - track index/count when available
4. Keep `FeedbackService.record_candidate()` as the only scope decision point.
5. Never aggregate feedback by organization, creator, topic, category, tag, or discovery route.
6. Keep progress-report callbacks responsible for progress recording only. Use `RateContentIntent` for explicit mid-session feedback rather than speaking a feedback question from an AudioPlayer callback.

## Acceptance Criteria

- A completed standalone track creates `feedbackKey == contentId` and `subjectType == "content"`.
- A completed non-publication track returned by organization filtering creates an individual content candidate.
- A completed non-publication track returned by creator filtering creates an individual content candidate.
- Topic, category, and tag searches create individual content candidates for each track.
- Multiple completed tracks from the same organization or creator do not collapse into one candidate.
- Multiple completed tracks from one publication create one candidate with `feedbackKey == "publication:<publicationId>"`.
- Publication candidate payload contains per-track listening information.
- `RateContentIntent` pauses the active track and resumes that same track after feedback.
- A publication selected with incomplete backend metadata retains the selected publication identity in playback state.
- Tests cover all six search/source contexts and both explicit mid-session and completion-triggered feedback.
