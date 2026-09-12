# Alexa Availability and Search Contract

## Endpoint responsibilities

`POST /alexa/availability` handles source discovery and source inventory.
It is the only endpoint used for recommendations. It returns creators and
organisations for the listener to choose from, or publications available from a
selected source.

`POST /alexa/search` handles catalogue search and playable content retrieval.
It accepts text, taxonomy, publisher, publication, content, date, location, and
search sort constraints. It does not accept `isRecommended` or
`sort: "recommended"`.

Both endpoints require `X-Api-Key`.

## Listener identity

`POST /alexa/listeners/register` and `/alexa/listeners/sync` return the canonical
`listenerId`. The skill persists that value and sends it on recommendation,
trending, normal search, local search, selected-source availability, playback,
feedback, follow, and report requests.

The backend resolves `listenerId` first. `alexaUserId` remains available as a
compatibility and alias fallback because Alexa identifiers may rotate. This keeps
location, listening history, publication ordering, feedback, and engagement tied
to one persistent listener record.

## Trending content search

```json
{
  "query": "",
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "filter": {},
  "sort": "trending",
  "page": 0,
  "limit": 20
}
```

Trending is handled only by `POST /alexa/search`. It returns and plays matching
catalogue content in trending order. A topic constrains the search results:

```json
{
  "query": "",
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "filter": {"categorySlugs": ["sport"]},
  "sort": "trending",
  "page": 0,
  "limit": 20
}
```

## Recommended source discovery

```json
{
  "filter": {},
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "isRecommended": true,
  "page": 0,
  "limit": 3
}
```

Recommendations combine the global trending rank with geographical relevance.
The backend uses coordinates or city supplied in `filter.location`; otherwise it
uses the canonical listener's registered coordinates or city.

```json
{
  "filter": {
    "location": {
      "city": "Manchester",
      "countryCode": "gb",
      "latitude": 53.4808,
      "longitude": -2.2426
    }
  },
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "isRecommended": true,
  "page": 0,
  "limit": 3
}
```

## Local source discovery

An explicit location is sent inside the availability filter:

```json
{
  "filter": {
    "location": {
      "city": "York",
      "countryCode": "gb",
      "latitude": 53.959,
      "longitude": -1.082
    }
  },
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "page": 0,
  "limit": 3
}
```

When the saved listener location should be used, send `isLocal: true` without a
location filter.

## City-based creator discovery

A generic creator request asks for a city. The resolved canonical location is
transient and is sent to availability with the creator-only boolean inside
`filter`:

```json
{
  "filter": {
    "isCreator": true,
    "location": {
      "city": "Manchester",
      "countryCode": "gb",
      "latitude": 53.4808,
      "longitude": -2.2426
    }
  },
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "page": 0,
  "limit": 3
}
```

The backend applies `isCreator: true` before pagination. Every page uses the
same location and creator filter. Alexa ignores any organizations returned in
error, keeps only the current page of up to three creator choices, and reloads
pages for next or previous navigation. The requested city and coordinates do
not update the listener profile or onboarding state.

## Source discovery response

The response preserves the existing `organizations` and `creators` fields and
the established pagination metadata.

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
      "id": "706cb68b-8059-407e-a696-0651018066cd",
      "name": "York Talking News"
    }
  ],
  "creators": [
    {
      "id": "4cd2cb60-1314-4f66-841d-e49ed4820a3b",
      "name": "A Reader"
    }
  ]
}
```

## Selected source availability

After the listener selects a creator or organisation, send exactly one singular
source identifier. Include listener identity so publication history ordering is
personal to that listener.

```json
{
  "filter": {
    "organizationId": "706cb68b-8059-407e-a696-0651018066cd"
  },
  "alexaUserId": "amzn1.ask.account.example",
  "listenerId": "6fd214d5-49d4-42f7-a982-a56cd16c9baa",
  "page": 0,
  "limit": 3
}
```

```json
{
  "page": 0,
  "limit": 3,
  "total": 2,
  "totalPages": 1,
  "remaining": 0,
  "hasMore": false,
  "nextPage": null,
  "publicationCount": 2,
  "standaloneTrackCount": 5,
  "publications": [
    {
      "publicationId": "b7f65f28-5ba0-4775-b4a1-8a58d821eff5",
      "title": "Morning Briefing",
      "trackCount": 8,
      "publishedAt": 1788518929,
      "updatedAt": 1788518929
    }
  ]
}
```

Publications the listener has not heard are returned first. Publications already
heard remain in the result set and move below every unheard publication. This is
calculated from the canonical listener's history, never from another listener's
activity.

## Voice selection flow

1. A trending request calls search with `sort: "trending"` and plays the first result.
2. A recommendation request calls availability with `isRecommended: true`.
3. A generic creator request asks for a city and calls availability with
   `filter.isCreator: true` plus the resolved location.
4. Alexa reads up to three eligible source names.
5. The listener selects a name or ordinal.
6. Alexa calls availability with the selected `creatorId` or `organizationId`.
7. If the selected source has publications and standalone tracks, Alexa asks which format
   the listener wants.
8. Alexa reads publication choices, or calls search with `isPublication: false`
   for standalone tracks.
9. A selected publication is loaded through search using `publicationIds`; a
   selected track is loaded using `contentIds`.

When a single publication container is selected, search always loads that
container independently of the requested track page and applies `page` and
`limit` to the embedded track collection. Pagination totals and navigation refer
to tracks, not to the single publication container.

An empty or failed availability response does not trigger an unrestricted search
or playback. The skill reports that no matching source was available and returns
to discovery.

## Search publication ordering

Search accepts `alexaUserId` and `listenerId`. When publication containers match,
it applies the same unheard-first ordering used by availability. Heard
publications remain available at the bottom. Standalone tracks retain their
normal search order.
