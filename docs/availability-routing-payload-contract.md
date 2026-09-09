# Availability Routing and Payload Contract

## Purpose

This document defines the required routing, request payloads, response handling,
playback safeguards, implementation work, tests, and live acceptance checks for
Alexa availability discovery.

The central rule is:

> Availability discovers whether a location, creator, organisation, or a
> supported combination of those scopes is available. Content search handles
> topics, tags, categories, publications, dates, recommendations, sorting, and
> other content constraints.

An empty availability result is final for that request. It must never be relaxed
into a broad or global search.

## Confirmed production defect

The live development Lambda received a request for Shalfleet and correctly sent:

```json
{
  "filter": {
    "location": {
      "city": "Shalfleet",
      "countryCode": "gb",
      "latitude": 50.7011,
      "longitude": -1.4152
    }
  },
  "page": 0,
  "limit": 3
}
```

The availability API returned zero organisations and zero creators. The skill
then incorrectly sent this unrestricted request to `/search`:

```json
{
  "query": "",
  "isLocal": false,
  "isRecommended": false,
  "filter": {},
  "page": 0,
  "limit": 3
}
```

That request returned global catalogue content and started playback. The same
incorrect path produced generic phrases such as `Playing content.` and could
leave resume state that later produced `You were listening to a recording.`

## Routing vocabulary

### Availability-compatible criteria

The following criteria are supported by `/availability`:

- one `organizationId`;
- one `creatorId`;
- one `location` object;
- any combination of those three fields.

The location object may contain:

- `city`;
- `countryCode`;
- `latitude`;
- `longitude`.

At least one usable availability-compatible criterion must be present.

### Search-only criteria

The presence of any of the following makes the request a `/search` request:

- a non-empty query or topic;
- tags;
- categories;
- a publication ID;
- a publication-only constraint;
- a published-from or published-to date;
- a recommendation constraint;
- latest, trending, popular, or another explicit sort;
- more than one creator ID;
- more than one organisation ID;
- any other content-level filter.

Availability-compatible criteria remain in the `/search` payload when combined
with search-only criteria. They must not be discarded.

## Routing decision matrix

| Resolved criteria | Endpoint | Availability `isLocal` field |
| --- | --- | ---: |
| Location only | `/availability` | omitted |
| Organisation only | `/availability` | `false` |
| Creator only | `/availability` | `false` |
| Location + organisation | `/availability` | omitted |
| Location + creator | `/availability` | omitted |
| Organisation + creator | `/availability` | `false` |
| Location + organisation + creator | `/availability` | omitted |
| No availability criterion and no content criterion | normal browse/search policy | derived |
| Location + query/topic | `/search` | `true` |
| Location + tag | `/search` | `true` |
| Location + category | `/search` | `true` |
| Location + publication | `/search` | `true` |
| Location + date range | `/search` | `true` |
| Location + recommended/latest/sort | `/search` | `true` |
| Creator + query/topic/tag/category | `/search` | derived from location |
| Organisation + query/topic/tag/category | `/search` | derived from location |
| Creator + organisation + any search-only criterion | `/search` | derived from location |

## Common availability request contract

Every `/availability` request must contain:

```json
{
  "filter": {},
  "alexaUserId": "<current Alexa user ID>",
  "page": 0,
  "limit": 3
}
```

Rules:

- `alexaUserId` is required and comes from the current Alexa request.
- `isLocal` must be omitted whenever `filter.location` is present.
- `isLocal` may be sent only when there is no location filter.
- Source-only requests currently send `isLocal: false`.
- `page` is zero-based.
- `limit` uses the Alexa choice page size, currently three.
- `/availability` does not receive `query`.
- Source IDs are singular in availability: `creatorId` and `organizationId`.
- Empty strings, empty objects, `null` values, and unsupported filter fields are
  removed before transmission.

## Complete availability request payloads

### A1. Location only

```json
{
  "filter": {
    "location": {
      "city": "Shalfleet",
      "countryCode": "gb",
      "latitude": 50.7011,
      "longitude": -1.4152
    }
  },
  "alexaUserId": "<current Alexa user ID>",
  "page": 0,
  "limit": 3
}
```

### A2. Organisation only

```json
{
  "filter": {
    "organizationId": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "page": 0,
  "limit": 3
}
```

### A3. Creator only

```json
{
  "filter": {
    "creatorId": "4fa85f64-5717-4562-b3fc-2c963f66afa7"
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "page": 0,
  "limit": 3
}
```

### A4. Location and organisation

```json
{
  "filter": {
    "organizationId": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "location": {
      "city": "Shalfleet",
      "countryCode": "gb",
      "latitude": 50.7011,
      "longitude": -1.4152
    }
  },
  "alexaUserId": "<current Alexa user ID>",
  "page": 0,
  "limit": 3
}
```

### A5. Location and creator

```json
{
  "filter": {
    "creatorId": "4fa85f64-5717-4562-b3fc-2c963f66afa7",
    "location": {
      "city": "Shalfleet",
      "countryCode": "gb",
      "latitude": 50.7011,
      "longitude": -1.4152
    }
  },
  "alexaUserId": "<current Alexa user ID>",
  "page": 0,
  "limit": 3
}
```

### A6. Organisation and creator

```json
{
  "filter": {
    "organizationId": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "creatorId": "4fa85f64-5717-4562-b3fc-2c963f66afa7"
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "page": 0,
  "limit": 3
}
```

### A7. Location, organisation, and creator

```json
{
  "filter": {
    "organizationId": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "creatorId": "4fa85f64-5717-4562-b3fc-2c963f66afa7",
    "location": {
      "city": "Shalfleet",
      "countryCode": "gb",
      "latitude": 50.7011,
      "longitude": -1.4152
    }
  },
  "alexaUserId": "<current Alexa user ID>",
  "page": 0,
  "limit": 3
}
```

## Availability pagination contract

Every subsequent page must preserve the complete original filter and
`alexaUserId`. It must continue to omit `isLocal` when location is present:

```json
{
  "filter": {
    "organizationId": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "creatorId": "4fa85f64-5717-4562-b3fc-2c963f66afa7",
    "location": {
      "city": "Shalfleet",
      "countryCode": "gb",
      "latitude": 50.7011,
      "longitude": -1.4152
    }
  },
  "alexaUserId": "<current Alexa user ID>",
  "page": 1,
  "limit": 3
}
```

No page may drop part of a combined filter.

## Search request contract

Search uses plural source ID arrays and flat location fields inside `filter`:

```json
{
  "query": "",
  "filter": {},
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "isRecommended": false,
  "page": 0,
  "limit": 3
}
```

Rules:

- `creatorIds`, `organizationIds`, and `publicationIds` are arrays.
- Location fields are flat inside the search filter.
- `isLocal` is top-level and is true when location is part of the search.
- A non-empty topic remains in `query` unless the resolver deliberately maps it
  to a canonical tag or category.
- Search must preserve every resolved constraint.
- Search must never be used to relax an empty availability result.

## Representative mixed search payloads

### S1. Location and category

```json
{
  "query": "",
  "filter": {
    "categorySlugs": ["community-news"],
    "city": "Shalfleet",
    "countryCode": "gb",
    "latitude": 50.7011,
    "longitude": -1.4152
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": true,
  "isRecommended": false,
  "page": 0,
  "limit": 3,
  "sort": "nearest"
}
```

### S2. Location and topic query

```json
{
  "query": "local history",
  "filter": {
    "city": "Shalfleet",
    "countryCode": "gb",
    "latitude": 50.7011,
    "longitude": -1.4152
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": true,
  "isRecommended": false,
  "page": 0,
  "limit": 3,
  "sort": "nearest"
}
```

### S3. Location and tag

```json
{
  "query": "",
  "filter": {
    "tags": ["sport"],
    "city": "Shalfleet",
    "countryCode": "gb",
    "latitude": 50.7011,
    "longitude": -1.4152
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": true,
  "isRecommended": false,
  "page": 0,
  "limit": 3,
  "sort": "nearest"
}
```

### S4. Creator and tag

```json
{
  "query": "",
  "filter": {
    "creatorIds": ["4fa85f64-5717-4562-b3fc-2c963f66afa7"],
    "tags": ["sport"]
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "isRecommended": false,
  "page": 0,
  "limit": 3
}
```

### S5. Organisation, creator, and tag

```json
{
  "query": "",
  "filter": {
    "organizationIds": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    "creatorIds": ["4fa85f64-5717-4562-b3fc-2c963f66afa7"],
    "tags": ["sport"]
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "isRecommended": false,
  "page": 0,
  "limit": 3
}
```

### S6. Location, creator, and tag

```json
{
  "query": "",
  "filter": {
    "creatorIds": ["4fa85f64-5717-4562-b3fc-2c963f66afa7"],
    "tags": ["sport"],
    "city": "Shalfleet",
    "countryCode": "gb",
    "latitude": 50.7011,
    "longitude": -1.4152
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": true,
  "isRecommended": false,
  "page": 0,
  "limit": 3,
  "sort": "nearest"
}
```

### S7. Source and publication

```json
{
  "query": "",
  "filter": {
    "organizationIds": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    "publicationIds": ["5fa85f64-5717-4562-b3fc-2c963f66afa8"]
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "isRecommended": false,
  "page": 0,
  "limit": 3
}
```

### S8. Location and date range

```json
{
  "query": "",
  "filter": {
    "city": "Shalfleet",
    "countryCode": "gb",
    "latitude": 50.7011,
    "longitude": -1.4152,
    "publishedFrom": 1788393600,
    "publishedTo": 1788998400
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": true,
  "isRecommended": false,
  "page": 0,
  "limit": 3,
  "sort": "nearest"
}
```

### S9. Recommended content from a location

```json
{
  "query": "",
  "filter": {
    "city": "Shalfleet",
    "countryCode": "gb",
    "latitude": 50.7011,
    "longitude": -1.4152
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": true,
  "isRecommended": true,
  "page": 0,
  "limit": 3,
  "sort": "recommended"
}
```

### S10. Latest content from a creator

```json
{
  "query": "",
  "filter": {
    "creatorIds": ["4fa85f64-5717-4562-b3fc-2c963f66afa7"]
  },
  "alexaUserId": "<current Alexa user ID>",
  "isLocal": false,
  "isRecommended": false,
  "page": 0,
  "limit": 3,
  "sort": "latest"
}
```

## Availability response contracts

### Source discovery response

Location and other source-discovery requests may return organisations and
creators:

```json
{
  "page": 0,
  "limit": 3,
  "total": 2,
  "totalPages": 1,
  "remaining": 0,
  "hasMore": false,
  "nextPage": null,
  "organizations": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "name": "Talking News Federation"
    }
  ],
  "creators": [
    {
      "id": "4fa85f64-5717-4562-b3fc-2c963f66afa7",
      "name": "Example Creator"
    }
  ]
}
```

The skill offers only candidates returned by the API. It says `next` only when
the normalized response proves that another page exists.

### Source content availability response

A source-scoped request may report publication and standalone-track inventory:

```json
{
  "page": 0,
  "limit": 3,
  "total": 4,
  "totalPages": 1,
  "remaining": 0,
  "hasMore": false,
  "nextPage": null,
  "publicationCount": 1,
  "standaloneTrackCount": 3,
  "publications": [
    {
      "publicationId": "5fa85f64-5717-4562-b3fc-2c963f66afa8",
      "title": "September edition",
      "trackCount": 3
    }
  ]
}
```

The skill may retrieve content only when this response positively reports
available publications or standalone tracks.

### Valid empty response

```json
{
  "page": 0,
  "limit": 3,
  "total": 0,
  "totalPages": 0,
  "remaining": 0,
  "hasMore": false,
  "nextPage": null,
  "publicationCount": 0,
  "standaloneTrackCount": 0,
  "organizations": [],
  "creators": [],
  "publications": []
}
```

This response is successful and authoritative. It is not an API failure and it
must not trigger `/search`.

## Empty-result behavior contract

When `/availability` succeeds with no matching availability:

1. Do not call `/search`.
2. Do not broaden, relax, or remove any filter.
3. Do not create an `AudioPlayer.Play` directive.
4. Do not create or replace a playback queue.
5. Do not change current, active, prepared, paused, or resume playback state.
6. Clear any availability selection dialog created for this request.
7. Keep the Alexa session open.
8. Speak a context-appropriate no-result response.

For a location request:

```text
I couldn't find a talking newspaper or creator near Shalfleet. What would you
like to listen to instead?
```

For a source request:

```text
I couldn't find anything available from that source. What would you like to
listen to instead?
```

The response must not claim that content was found, must not say `Playing
content`, and must not introduce unrelated catalogue content.

## Availability failure behavior contract

Transport failure, timeout, invalid response, or non-success HTTP status is
different from a valid empty response.

Required behavior:

1. Do not call `/search`.
2. Do not alter playback or queue state.
3. Clear request-owned availability dialog state when appropriate.
4. Keep the Alexa session open.
5. Tell the listener availability could not be checked and invite a retry.

Example:

```text
I had trouble finding content in Everton just now. Please say the name of a
talking newspaper, creator, publication, or city you would like to listen to.
```

## Post-availability content retrieval

A `/search` call after availability is allowed only when availability positively
reports content that must be retrieved for playback.

Permitted examples:

- `standaloneTrackCount` is greater than zero and the listener chooses tracks;
- the listener chooses a returned publication and its content must be loaded;
- the listener selects a returned creator or organisation whose availability
  response reports playable inventory.

The retrieval request must remain constrained to the selected source or
publication. It is not permitted to issue an empty global search.

If both `publicationCount` and `standaloneTrackCount` are zero and no
publications are returned, retrieval is not permitted.

## Playback and resume safeguards

An empty or failed availability operation must not change:

- `activePlayback`;
- `preparedPlayback`;
- `playbackQueue`;
- current content ID, title, creator, organisation, or publication fields;
- resume offset;
- discovery source or discovery context;
- pending feedback state.

This prevents the availability defect from producing:

- unrelated global playback;
- `Playing content.`;
- `Now playing` without meaningful context;
- `You were listening to a recording.` on the next launch;
- feedback prompts for content the listener did not request.

## Required implementation changes

### `src/models/availability_data.py`

- Replace the one-source-only scope rule with a rule that accepts any supported
  combination of location, one creator, and one organisation.
- Reject availability routing when any search-only criterion is active.
- Reject multiple creator IDs or multiple organisation IDs.
- Add one canonical transformation from plural resolver/search source fields to
  singular availability fields.
- Preserve location when it is combined with creator or organisation.

### `src/models/availability.py`

- Build the complete availability filter from the resolved payload.
- Pass `alexaUserId` on every request and omit `isLocal` whenever location is filtered.
- Preserve combined filters in dialog context and pagination.
- Separate successful-empty handling from failed-request handling.
- Remove unrestricted fallback search from both paths.
- Allow content retrieval only after positive inventory is reported.
- Clear only availability-owned dialog state on no result or failure.
- Leave playback, queue, resume, and feedback state untouched.

### `src/clients/availability.py`

- Accept one or more supported availability filter fields.
- Validate at most one non-empty creator ID and one non-empty organisation ID.
- Validate the location object and its allowed fields.
- Reject unsupported or empty filters.
- Preserve every valid combined filter field.
- Keep pagination normalization authoritative so `next` is never offered on the
  final page.

### `src/clients/hear.py`

- Serialize `alexaUserId` at the top level of `/availability` requests.
- Serialize `isLocal` only when the request has no location filter.
- Preserve the complete normalized combined filter.
- Keep `page` and `limit` intact.
- Keep logs privacy-safe while logging the presence of Alexa identity and the
  filter keys used.

### `src/alexa/availability_speech.py`

- Add distinct speech for valid no results and availability failure.
- Include the requested city when it is safe and available.
- Do not use loading-failure wording for a genuine zero-result response.
- Do not mention `next` without a proven next page.

### Tests

- Replace tests that expect location to be discarded when combined with a
  creator or organisation.
- Remove tests that expect global fallback search after empty availability.
- Retain source-track retrieval tests only when availability reports a positive
  standalone-track count.

## Required test matrix

### Routing tests

- location only routes to availability;
- creator only routes to availability;
- organisation only routes to availability;
- location + creator routes to availability;
- location + organisation routes to availability;
- creator + organisation routes to availability;
- location + creator + organisation routes to availability;
- location + category routes to search;
- location + topic routes to search;
- location + tag routes to search;
- creator + tag routes to search;
- organisation + category routes to search;
- creator + organisation + tag routes to search;
- publication, date, recommended, and explicit-sort requests route to search;
- multiple creator or organisation IDs route to search.

### Availability client tests

- all seven supported request payloads serialize exactly;
- `alexaUserId` is included;
- `isLocal` is absent exactly when location is present;
- combined filters survive normalization;
- invalid filter fields are rejected before an HTTP call;
- page and limit are preserved;
- final-page metadata cannot produce a false `next` offer.

### Empty and failure tests

- valid empty source discovery does not call search;
- valid empty source inventory does not call search;
- failed availability does not call search;
- no-result response contains no audio directive;
- failure response contains no audio directive;
- active playback is unchanged;
- playback queue is unchanged;
- resume state is unchanged;
- availability dialog is cleared;
- session remains open with a useful reprompt.

### Positive inventory tests

- positive standalone-track count permits constrained track retrieval;
- returned publication permits constrained publication retrieval;
- retrieval retains the selected source/publication ID;
- retrieval never becomes an empty global search.

## Verification commands

```powershell
python -m pytest -q tests/test_availability_flow.py tests/test_api_client.py
python -m ruff check src tests
python -m compileall -q main.py src config
python .agents/skills/hear-architecture-refactor/scripts/audit_architecture.py . --strict
python -m pytest -q
git diff --check
```

## Development deployment acceptance test

Use the real Alexa development skill and request Shalfleet.

Expected CloudWatch sequence:

```text
resolver -> confirmed location request
/availability -> filter.location=Shalfleet, alexaUserIdPresent=true, isLocal=omitted
/availability response -> total=0, organizations=[], creators=[]
Alexa no-result response
```

The same request must produce none of the following:

```text
/search with filter={}
/search with isLocal=false
AudioPlayer.Play
AudioPlayer.PlaybackStarted
Playing content.
You were listening to a recording.
```

Repeat the live test for each supported combined availability payload and at
least one mixed search payload from each search-only category.

## Definition of done

The work is complete only when:

- all seven availability combinations reach `/availability` with the exact
  contract defined above;
- mixed content requests reach `/search` without losing constraints;
- every availability request includes `alexaUserId` and omits `isLocal` for location filters;
- empty and failed availability never trigger search or playback;
- positive inventory still supports constrained content retrieval;
- pagination never offers a nonexistent next page;
- no-result handling leaves previous playback and resume state untouched;
- focused and full automated tests pass;
- strict architecture audit passes with zero errors and warnings;
- the Shalfleet live development test matches the expected CloudWatch sequence.
