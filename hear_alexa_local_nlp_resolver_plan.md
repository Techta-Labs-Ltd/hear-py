# Hear Alexa Local NLP Resolver & Search Architecture Plan

**Status:** Proposed production architecture
**Language:** Python
**Runtime:** AWS Lambda / Alexa Skill
**Search engine:** Existing Hear backend + Meilisearch
**Taxonomy source:** `https://f003.backblazeb2.com/file/OldAlexa/runtime/taxonomy/v3/manifest.json`

---

## 1. Objective

The main problem is not Meilisearch itself.

The main problem is converting natural Alexa requests such as:

```text
find me the latest sport track from david
```

or:

```text
play news from david beard about council tax from last week
```

into the **correct structured Hear search request**.

The resolver must understand:

- what the user wants to do;
- which words represent categories;
- which words represent creators;
- which words represent organizations;
- which words represent publications;
- which words represent locations;
- which words represent tags;
- which words are actual free-text search terms;
- whether the user wants local content;
- whether the user wants recommendations;
- what time/date range the user means;
- what sorting strategy is implied;
- which words are merely conversational filler.

The result must be produced **locally and very quickly inside the Alexa Lambda**.

The previous gRPC resolver architecture should be removed.

---

# 2. Final High-Level Architecture

```text
Alexa User
   |
   | "find me the latest sport track from david"
   v
Alexa Skill / Python Lambda
   |
   +-----------------------------------------------+
   | Local Resolver                               |
   |                                               |
   |  1. Normalize utterance                       |
   |  2. Detect search mode / modifiers            |
   |  3. Parse dates and temporal expressions      |
   |  4. Match taxonomy entities                   |
   |  5. Use context to disambiguate entities      |
   |  6. Apply fuzzy fallback where needed         |
   |  7. Extract residual free-text query          |
   |  8. Build Hear Search Request                 |
   +-----------------------------------------------+
   |
   | HTTPS JSON
   v
Hear Backend Search API
   |
   v
Meilisearch
   |
   v
Search Results
   |
   v
Alexa response / playback
```

There is **no gRPC resolver service**.

There is **no extra network call for NLP**.

The resolver is a Python module loaded directly inside the Alexa Lambda process.

---

# 3. Existing Hear Search Contract

The resolver must ultimately produce requests compatible with the existing Hear catalog search API.

Example:

```json
{
  "alexaUserId": "amzn1.ask.account.example",
  "filter": {
    "categorySlugs": [
      "news",
      "politics"
    ],
    "city": "lagos",
    "countryCode": "ng",
    "creatorIds": [
      "00000000-0000-0000-0000-000000000001"
    ],
    "organizationIds": [
      "00000000-0000-0000-0000-000000000002"
    ],
    "tags": [
      "breaking-news",
      "local"
    ]
  },
  "isLocal": true,
  "isRecommended": true,
  "limit": 20,
  "page": 0,
  "query": "morning news",
  "sort": "recommended"
}
```

The search API semantics are:

- `query`
  - free-text search;
  - searches track titles and suggested titles;
  - should contain only unresolved topical words;
  - should **not** contain words already converted into filters.

- `filter`
  - exact facet matching;
  - all fields optional;
  - omit `filter` entirely when no exact filters exist.

Supported filter concepts:

```text
categorySlugs
tags
creatorIds
organizationIds
publicationIds
city
countryCode
```

- `isLocal`
  - true when the user explicitly asks for local/nearby content;
  - triggers geo-radius search around the listener's registered location.

- `isRecommended`
  - true when the user requests personalized/recommended content;
  - uses listener taste profile, listening categories/tags and followed creators.

- `sort`
  - should be determined by the user's language.

Examples:

```text
latest / newest / recent
    -> latest

recommended / for me / something I would like
    -> recommended

otherwise
    -> recommended or relevance depending on product policy
```

---

# 4. Core Design Principle

The resolver must separate:

```text
FILTERABLE MEANING
```

from:

```text
FREE-TEXT SEARCH MEANING
```

Example:

```text
find me the latest sport track from david about arsenal
```

The wrong approach is:

```json
{
  "query": "latest sport track david arsenal"
}
```

The correct interpretation is:

```text
find me
    -> command language

latest
    -> sort=latest

sport
    -> categorySlugs=["sports"]

track
    -> content noun / command language

from david
    -> creatorIds=[David's UUID]

about arsenal
    -> query="arsenal"
```

Result:

```json
{
  "alexaUserId": "USER_ID",
  "filter": {
    "categorySlugs": [
      "sports"
    ],
    "creatorIds": [
      "DAVID_CREATOR_UUID"
    ]
  },
  "isLocal": false,
  "isRecommended": false,
  "limit": 20,
  "page": 0,
  "query": "arsenal",
  "sort": "latest"
}
```

This separation is the most important rule in the entire resolver.

---

# 5. Resolver Output Model

Internally, the resolver should first create a structured object before producing the final API payload.

Recommended model:

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ResolvedEntity:
    entity_type: str
    entity_id: Optional[str]
    canonical_value: str
    original_text: str
    confidence: float
    method: str


@dataclass
class TemporalRange:
    start_timestamp: Optional[int] = None
    end_timestamp: Optional[int] = None
    original_text: Optional[str] = None


@dataclass
class SearchPlan:
    query: str = ""

    category_slugs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    creator_ids: list[str] = field(default_factory=list)
    organization_ids: list[str] = field(default_factory=list)
    publication_ids: list[str] = field(default_factory=list)

    city: Optional[str] = None
    country_code: Optional[str] = None

    is_local: bool = False
    is_recommended: bool = False

    sort: str = "recommended"

    page: int = 0
    limit: int = 20

    temporal: Optional[TemporalRange] = None

    confidence: float = 1.0

    entities: list[ResolvedEntity] = field(default_factory=list)
```

The backend API payload is generated from this model.

---

# 6. Python Technology Stack

Use the tools already available in the Alexa project.

## Required

```text
Python
spaCy
RapidFuzz
Pydantic or dataclasses
boto3
requests or httpx
zoneinfo
```

Suggested packages:

```bash
pip install spacy rapidfuzz pydantic httpx
```

No Semantic Router is required for the first production version.

No remote LLM is required for the normal search path.

No gRPC is required.

---

# 7. NLP Pipeline

The resolver should work as a staged pipeline.

```text
Raw Alexa Utterance
        |
        v
Normalization
        |
        v
Command / Modifier Detection
        |
        v
Temporal Parsing
        |
        v
Exact Taxonomy Matching
        |
        v
Contextual Entity Resolution
        |
        v
Scoped Fuzzy Fallback
        |
        v
Residual Query Extraction
        |
        v
SearchPlan
        |
        v
Hear API Payload
```

Each stage should claim spans of the sentence.

Once a span has been confidently resolved, later stages should not reinterpret it.

---

# 8. Stage 1 — Normalization

Always preserve both:

```python
raw_text
normalized_text
```

Example:

```text
Raw:
"Find me the latest Sport track from David."

Normalized:
"find me the latest sport track from david"
```

Normalization can include:

- lowercase;
- punctuation normalization;
- whitespace normalization;
- apostrophe normalization;
- known Alexa ASR aliases;
- known domain aliases.

Do **not** remove important context words yet.

Keep:

```text
from
by
in
near
around
about
on
since
for
```

because they provide meaning.

---

# 9. Stage 2 — Command and Modifier Detection

Some words describe what Alexa should do rather than what Meilisearch should search.

Examples:

```text
find me
play me
give me
let me hear
I want to hear
search for
put on
```

These are command phrases.

They should normally be removed from the final free-text query.

---

## Sort modifiers

Examples:

```text
latest
newest
most recent
recent
today's latest
```

should generally produce:

```json
{
  "sort": "latest"
}
```

Examples:

```text
recommended
recommend something
something for me
something I might like
something based on what I listen to
```

should produce:

```json
{
  "isRecommended": true,
  "sort": "recommended"
}
```

---

# 10. Stage 3 — Temporal Parsing

Temporal expressions must be resolved **before general entity matching**.

This avoids ambiguity in phrases such as:

```text
from monday
```

versus:

```text
from david
```

The first is a date expression.

The second is probably a creator or organization.

---

## Required temporal rules

Implement the most common Alexa phrases directly.

### Today

```text
today
today's
```

Meaning:

```text
start of today -> now
```

---

### Yesterday

```text
yesterday
yesterday's
```

Meaning:

```text
yesterday 00:00 -> today 00:00
```

---

### Last week

```text
last week
```

Meaning:

```text
previous calendar week
```

---

### This week

```text
this week
```

Meaning:

```text
start of current week -> now
```

---

### From Monday

```text
from monday
```

Meaning:

```text
most recent Monday at 00:00 -> now
```

---

### On Monday

```text
on monday
```

Meaning:

```text
Monday 00:00 -> Tuesday 00:00
```

---

### Since Monday

```text
since monday
```

Meaning:

```text
most recent Monday -> now
```

---

## Important

The existing search API payload shown above does not currently expose a date field.

Therefore one of these approaches is required:

### Preferred

Extend the backend search request with:

```json
{
  "publishedFrom": 1784502000,
  "publishedTo": 1785106800
}
```

The backend then adds the appropriate Meilisearch date filters.

### Alternative

Add date fields inside `filter` if the backend contract is designed that way.

Do not convert time phrases into `query`.

Wrong:

```json
{
  "query": "sport last week"
}
```

Correct:

```json
{
  "query": "",
  "filter": {
    "categorySlugs": ["sports"]
  },
  "publishedFrom": 1784502000,
  "publishedTo": 1785106800
}
```

---

# 11. Stage 4 — Taxonomy Entity Matching

Use spaCy `PhraseMatcher`.

Recommended:

```python
import spacy
from spacy.matcher import PhraseMatcher


nlp = spacy.blank("en")

matcher = PhraseMatcher(
    nlp.vocab,
    attr="LOWER"
)
```

There is no need to load a large spaCy statistical model for the basic taxonomy resolver.

---

# 12. Taxonomy Entity Types

The resolver should understand at least:

```text
CATEGORY
TAG
CREATOR
ORGANIZATION
PUBLICATION
LOCATION
```

Each taxonomy item needs:

```text
stable ID or slug
canonical name
aliases
entity type
```

Example internal record:

```json
{
  "entityType": "creator",
  "id": "a81a4f95-...",
  "canonical": "David Beard",
  "aliases": [
    "David Beard",
    "David",
    "Dave Beard"
  ]
}
```

Example category:

```json
{
  "entityType": "category",
  "slug": "sports",
  "canonical": "Sports",
  "aliases": [
    "sport",
    "sports",
    "sport news",
    "sporting news"
  ]
}
```

---

# 13. PhraseMatcher Strategy

Register canonical names and approved aliases.

Example:

```python
matcher.add(
    "CREATOR:david-uuid",
    [
        nlp.make_doc("David Beard"),
        nlp.make_doc("David"),
        nlp.make_doc("Dave Beard")
    ]
)

matcher.add(
    "CATEGORY:sports",
    [
        nlp.make_doc("sports"),
        nlp.make_doc("sport")
    ]
)
```

Then:

```text
find me the latest sport track from david
```

can produce:

```text
sport
    -> CATEGORY:sports

david
    -> CREATOR:david-uuid
```

---

# 14. Context-Aware Entity Resolution

Exact matching alone is not enough.

The resolver must use surrounding words to determine what a matched phrase means.

---

## Context hints

### `by`

```text
by david
```

Strongly suggests:

```text
CREATOR
```

Second possibility:

```text
ORGANIZATION
```

---

### `from`

```text
from david
```

After temporal parsing has ruled out a date, strongly suggests:

```text
CREATOR
ORGANIZATION
PUBLICATION
```

---

### `in`

```text
in lagos
```

Strongly suggests:

```text
LOCATION
```

---

### `near`

```text
near me
near lagos
```

Strongly suggests:

```text
isLocal=true
```

or a location filter.

---

### `around`

```text
around lagos
```

Strongly suggests:

```text
LOCATION
```

---

### `about`

```text
about football
```

Can represent:

```text
CATEGORY
TAG
```

If no strong taxonomy match exists, leave it as:

```text
query
```

---

### `from HRA`

May represent:

```text
ORGANIZATION
```

not creator.

---

# 15. Context Scoring

Use a simple deterministic score.

Conceptually:

```text
score =
    lexical score
  + context bonus
  + alias quality bonus
  + longest span bonus
  - ambiguity penalty
```

Recommended starting points:

```text
Exact canonical match:
1.00

Exact alias:
0.98

High fuzzy:
0.85 - 0.94

Weak fuzzy:
reject
```

Context bonuses:

```text
"by <creator>"
+ strong creator bonus

"in <location>"
+ strong location bonus

"about <category>"
+ category/tag bonus

"from <organization>"
+ organization bonus
```

---

# 16. Longest Span Wins

This is critical.

Suppose the utterance contains:

```text
Havering Residents Association
```

The taxonomy may also match:

```text
Havering
```

as a location.

The resolver should prefer:

```text
Havering Residents Association
```

because it is the longer exact organization match.

Only use the nested `Havering` match if context clearly requires it.

---

# 17. Stage 5 — Fuzzy Matching

Use RapidFuzz only when exact/alias matching fails.

Do **not** fuzzy match every possible phrase against every taxonomy record.

Example:

```text
news by david bird
```

Context says:

```text
by ...
```

Therefore fuzzy search only:

```text
CREATOR aliases
```

Possible candidate:

```text
David Beard
score: 93
```

Then resolve:

```text
CREATOR = David Beard
```

---

## Fuzzy thresholds

Start conservatively.

### Creators

```text
>= 90
```

preferred.

### Organizations

```text
>= 90
```

preferred.

### Publications

```text
>= 90
```

preferred.

### Locations

```text
>= 90
```

preferred.

### Categories/tags

Potentially slightly lower:

```text
>= 85
```

because these are broader concepts.

These thresholds must eventually be tuned using real Alexa transcription logs.

---

# 18. Do Not Use Semantic Similarity for Proper Names

Do not let an embedding model decide that:

```text
David Beard
```

is semantically close to another person.

Proper names should use:

```text
exact
    ->
alias
    ->
phonetic/fuzzy
    ->
reject or retain as query
```

Semantic similarity can be considered later for broader concepts.

Example:

```text
soccer
```

could semantically map to:

```text
football
sports
```

But semantic similarity should not be the main engine for:

```text
creator
organization
publication
location
```

---

# 19. Stage 6 — Residual Query Extraction

This stage is essential.

After the resolver identifies:

- command words;
- temporal phrases;
- entity spans;
- sort modifiers;
- local/recommended modifiers;
- contextual prepositions;

the remaining meaningful words become:

```json
{
  "query": "..."
}
```

---

## Example 1

```text
play news from david about council tax
```

Resolved:

```text
play
    -> command

news
    -> category=news

from david
    -> creator=David

about
    -> connector
```

Remaining:

```text
council tax
```

Therefore:

```json
{
  "query": "council tax"
}
```

---

## Example 2

```text
find me the latest sport track from david
```

Resolved:

```text
find me
    -> command

latest
    -> sort

sport
    -> category

track
    -> generic content noun

from david
    -> creator
```

Remaining:

```text
nothing
```

Therefore:

```json
{
  "query": ""
}
```

---

# 20. Full Example — Latest Sport Track from David

Input:

```text
find me the latest sport track from david
```

Interpretation:

```text
find me
    -> SEARCH/PLAY

latest
    -> sort=latest

sport
    -> categorySlugs=["sports"]

track
    -> generic track noun

from david
    -> creatorIds=[DAVID_UUID]

residual
    -> ""
```

Final request:

```json
{
  "alexaUserId": "amzn1.ask.account.example",
  "filter": {
    "categorySlugs": [
      "sports"
    ],
    "creatorIds": [
      "DAVID_UUID"
    ]
  },
  "isLocal": false,
  "isRecommended": false,
  "limit": 20,
  "page": 0,
  "query": "",
  "sort": "latest"
}
```

If Alexa is supposed to immediately play only the newest item, the skill may internally request:

```json
{
  "limit": 1
}
```

depending on backend/playback architecture.

---

# 21. Example — Latest Local News

Input:

```text
play the latest local news
```

Interpretation:

```text
latest
    -> sort=latest

local
    -> isLocal=true

news
    -> categorySlugs=["news"]
```

Payload:

```json
{
  "alexaUserId": "USER_ID",
  "filter": {
    "categorySlugs": [
      "news"
    ]
  },
  "isLocal": true,
  "isRecommended": false,
  "limit": 20,
  "page": 0,
  "query": "",
  "sort": "latest"
}
```

Do not necessarily add:

```json
{
  "tags": ["local"]
}
```

unless `local` is explicitly defined as both a taxonomy tag and intended exact facet.

`isLocal=true` already has distinct geo-search meaning.

---

# 22. Example — Recommended Sports

Input:

```text
recommend some sport for me
```

Interpretation:

```text
sport
    -> categorySlugs=["sports"]

recommend / for me
    -> isRecommended=true
    -> sort=recommended
```

Payload:

```json
{
  "alexaUserId": "USER_ID",
  "filter": {
    "categorySlugs": [
      "sports"
    ]
  },
  "isLocal": false,
  "isRecommended": true,
  "limit": 20,
  "page": 0,
  "query": "",
  "sort": "recommended"
}
```

---

# 23. Example — Local Recommended News

Input:

```text
give me some recommended local news
```

Payload:

```json
{
  "alexaUserId": "USER_ID",
  "filter": {
    "categorySlugs": [
      "news"
    ]
  },
  "isLocal": true,
  "isRecommended": true,
  "limit": 20,
  "page": 0,
  "query": "",
  "sort": "recommended"
}
```

---

# 24. Example — News about Reservoir from David

Input:

```text
play news about the reservoir from david
```

Interpretation:

```text
news
    -> category

reservoir
    -> free-text query

david
    -> creator
```

Payload:

```json
{
  "alexaUserId": "USER_ID",
  "filter": {
    "categorySlugs": [
      "news"
    ],
    "creatorIds": [
      "DAVID_UUID"
    ]
  },
  "isLocal": false,
  "isRecommended": false,
  "limit": 20,
  "page": 0,
  "query": "reservoir",
  "sort": "recommended"
}
```

---

# 25. Example — Politics in Lagos

Input:

```text
find politics in lagos
```

Interpretation:

```text
politics
    -> categorySlugs=["politics"]

in lagos
    -> city="lagos"
```

Possible payload:

```json
{
  "alexaUserId": "USER_ID",
  "filter": {
    "categorySlugs": [
      "politics"
    ],
    "city": "lagos",
    "countryCode": "ng"
  },
  "isLocal": false,
  "isRecommended": false,
  "limit": 20,
  "page": 0,
  "query": "",
  "sort": "recommended"
}
```

If the user says:

```text
politics near me
```

prefer:

```json
{
  "isLocal": true
}
```

rather than manually forcing a city.

---

# 26. Taxonomy Architecture

Current manifest:

```text
https://f003.backblazeb2.com/file/OldAlexa/runtime/taxonomy/v3/manifest.json
```

The taxonomy includes data such as:

```text
aliases
categories
creators
locations
organizations
publications
tags
```

The resolver should never need to call the backend to identify these entities during a normal search.

The active taxonomy should live locally in Lambda memory.

---

# 27. Static vs Dynamic Taxonomy

## Static

Locations are mostly static.

Therefore:

```text
locations.json
```

should be bundled with the Lambda deployment package or a Lambda Layer.

It should not be regenerated or downloaded during every dynamic taxonomy update.

Example structure:

```text
alexa_skill/
  taxonomy/
    static/
      locations.json
```

---

## Dynamic

Likely dynamic:

```text
aliases.json
categories.json
creators.json
organizations.json
publications.json
tags.json
```

These can change as content creators and backend data change.

They should be refreshed independently.

---

# 28. Manifest Design

Use a manifest containing:

```json
{
  "schemaVersion": 3,
  "revision": "2026-07-29T00:30:00Z-8b3e92",
  "generatedAt": "2026-07-29T00:30:00Z",
  "files": [
    {
      "name": "aliases.json",
      "hash": "HASH",
      "mutable": true
    },
    {
      "name": "creators.json",
      "hash": "HASH",
      "mutable": true
    },
    {
      "name": "locations.json",
      "hash": "HASH",
      "mutable": false
    }
  ]
}
```

Do not use:

```text
version=3
```

as the only update detector.

`3` is a schema/data format version.

A separate revision should identify a specific generated taxonomy snapshot.

---

# 29. Webhook Refresh Architecture

When dynamic taxonomy changes:

```text
Hear Backend
    |
    +--> generate changed taxonomy JSON
    |
    +--> upload JSON to Backblaze
    |
    +--> write/update manifest
    |
    +--> send webhook
             |
             v
       AWS webhook Lambda/API
             |
             v
       DynamoDB revision record
```

Example DynamoDB item:

```json
{
  "id": "current",
  "revision": "2026-07-29T00:30:00Z-8b3e92",
  "generatedAt": "2026-07-29T00:30:00Z",
  "hashes": {
    "aliases.json": "...",
    "categories.json": "...",
    "creators.json": "...",
    "organizations.json": "...",
    "publications.json": "...",
    "tags.json": "..."
  }
}
```

The webhook does **not** attempt to directly modify Alexa Lambda memory.

Different Lambda execution environments have separate memory.

Instead, the webhook publishes the latest revision to shared state.

---

# 30. Lambda Taxonomy Refresh Flow

At module level:

```python
taxonomy_manager = TaxonomyManager()
resolver = Resolver(taxonomy_manager.snapshot)
```

Then on each search:

```python
latest_revision = revision_store.get_current()

if latest_revision != taxonomy_manager.revision:
    taxonomy_manager.refresh(latest_revision)

plan = resolver.resolve(utterance)
```

The shared revision check is tiny.

Do not download the Backblaze manifest on every normal request.

Only download taxonomy when the revision differs.

---

# 31. Changed Files Only

The manager compares hashes.

Example:

```text
Current Lambda snapshot:

aliases        hash=A
creators       hash=B
categories     hash=C
tags           hash=D

New revision:

aliases        hash=A
creators       hash=NEW_B
categories     hash=C
tags           hash=NEW_D
```

Download only:

```text
creators.json
tags.json
```

Do not download:

```text
aliases.json
categories.json
locations.json
```

---

# 32. Atomic Taxonomy Refresh

Never overwrite the live matcher while files are still downloading.

Correct process:

```text
1. Detect new revision
2. Download changed JSON to temporary location
3. Verify HTTP success
4. Verify file hash
5. Parse JSON
6. Validate schema
7. Build lookup tables
8. Build new spaCy matcher
9. Run smoke tests
10. Atomic swap active snapshot
```

If any step fails:

```text
keep using previous working taxonomy
```

Do not make Alexa unavailable because one taxonomy update is malformed.

---

# 33. `/tmp` Cache

Use both:

```text
RAM
```

and:

```text
/tmp
```

RAM stores:

```text
compiled matcher
lookup dictionaries
active snapshot
```

`/tmp` stores:

```text
downloaded JSON files
manifest/revision snapshot
```

Possible structure:

```text
/tmp/hear-taxonomy/
  aliases.json
  categories.json
  creators.json
  organizations.json
  publications.json
  tags.json
  revision.json
```

On a reused Lambda execution environment this can reduce unnecessary downloads.

---

# 34. Fast Lookup Structures

Build optimized dictionaries at snapshot creation time.

Example:

```python
creator_aliases = {
    "david": "creator_uuid",
    "david beard": "creator_uuid",
    "dave beard": "creator_uuid",
}
```

Categories:

```python
category_aliases = {
    "sport": "sports",
    "sports": "sports",
    "football": "sports"
}
```

Organizations:

```python
organization_aliases = {
    "hra": "organization_uuid",
    "havering residents association": "organization_uuid"
}
```

Locations:

```python
location_aliases = {
    "lagos": {
        "city": "lagos",
        "countryCode": "ng"
    }
}
```

Exact dictionary lookup should happen before fuzzy matching.

---

# 35. Matching Priority

Recommended order:

```text
1. Temporal expressions
2. Exact canonical names
3. Exact aliases
4. Context-aware exact matches
5. Scoped fuzzy matching
6. Optional category/tag semantic fallback
7. Residual query
```

Do not reverse this order.

---

# 36. Search Intent vs Alexa Built-In Intents

Alexa can continue handling obvious playback commands:

```text
stop
pause
resume
next
previous
repeat
help
```

The local NLP resolver primarily handles the open-ended content-search utterance.

Examples:

```text
find me ...
play ...
give me ...
I want ...
let me hear ...
search for ...
```

There is no need to run Semantic Router across every Alexa built-in playback command.

---

# 37. Local Search Semantics

The resolver should distinguish these.

### "near me"

```json
{
  "isLocal": true
}
```

### "local news"

Usually:

```json
{
  "isLocal": true,
  "filter": {
    "categorySlugs": ["news"]
  }
}
```

### "news in lagos"

Usually:

```json
{
  "filter": {
    "categorySlugs": ["news"],
    "city": "lagos",
    "countryCode": "ng"
  }
}
```

These are related but not identical operations.

---

# 38. Recommendation Semantics

Examples:

```text
recommend something
something for me
what should I listen to
something I would like
give me my usual news
```

should enable:

```json
{
  "isRecommended": true,
  "sort": "recommended"
}
```

Additional explicit filters should remain.

Example:

```text
recommend sport from david
```

becomes:

```json
{
  "filter": {
    "categorySlugs": ["sports"],
    "creatorIds": ["DAVID_UUID"]
  },
  "isRecommended": true,
  "sort": "recommended",
  "query": ""
}
```

Recommendation does not mean dropping the user's explicit filters.

---

# 39. Search Sorting Rules

Suggested policy:

```text
latest / newest / recent
    -> latest

recommended / for me / something I would like
    -> recommended

popular / trending
    -> popularity/trending sort if backend supports it

no explicit sorting language
    -> recommended for personalized browse
       OR relevance for explicit query searches
```

Recommended default distinction:

```text
query != ""
    -> relevance/recommended depending backend design

query == "" and browse request
    -> recommended
```

---

# 40. Confidence Rules

Recommended starting thresholds:

```text
>= 0.92
    safe exact hard filter

0.85 - 0.91
    use only when strong contextual support exists

< 0.85
    do not silently convert into a hard filter
```

Example:

```text
"from davit"
```

If fuzzy match to David is only:

```text
0.76
```

do not hard-filter on David.

A wrong creator filter is worse than a broader search.

---

# 41. Ambiguity Strategy

Suppose:

```text
play david from havering
```

Possible interpretation:

```text
David -> creator
Havering -> location
```

If exact/context confidence is high:

```json
{
  "filter": {
    "creatorIds": ["DAVID_UUID"],
    "city": "havering-city-value"
  }
}
```

If an entity is ambiguous, generate candidate interpretations internally.

Example:

```text
Candidate A:
creator=David
location=Havering

score=0.96

Candidate B:
query="david"
organization=Havering ...

score=0.61
```

Use candidate A.

Do not send multiple backend searches during every normal request.

---

# 42. Controlled Zero-Result Fallback

Primary search:

```text
creator=David
category=sports
date=last week
```

If zero results:

do not immediately remove everything.

Relax carefully.

Priority:

```text
explicit creator
    -> strongest, normally keep

explicit organization
    -> strong, normally keep

explicit publication
    -> strong, normally keep

explicit location
    -> strong

category
    -> medium

date
    -> may widen when wording is vague

query
    -> allow Meilisearch typo tolerance
```

Only one secondary search should normally be attempted to protect latency.

---

# 43. Backend Responsibilities

The Lambda resolver decides meaning.

The backend decides Meilisearch implementation.

The backend should:

```text
validate request
convert filters to Meilisearch filter syntax
apply date filters
apply sort
apply query
apply personalization
apply geo search
execute search
return normalized results
```

Lambda should not contain Meilisearch credentials.

---

# 44. Searchable vs Filterable Data

Exact facets should be filters.

Examples:

```text
categorySlugs
creatorIds
organizationIds
publicationIds
tags
city
countryCode
```

Free-text should be:

```text
track title
suggested title
other intentionally searchable fields
```

Do not use `query` as a substitute for exact creator/category filtering.

---

# 45. Example Backend Translation

Resolver payload:

```json
{
  "query": "reservoir",
  "filter": {
    "categorySlugs": ["news"],
    "creatorIds": ["DAVID_UUID"]
  },
  "sort": "latest"
}
```

Conceptual Meilisearch search:

```text
q = reservoir

filter =
categorySlugs = news
AND creatorIds = DAVID_UUID

sort =
publishedAt DESC
```

The exact syntax remains backend-specific.

---

# 46. Performance Requirements

The NLP resolver must be designed so that the backend/search network call is the dominant latency, not NLP.

Suggested warm targets:

```text
Normalization:
< 2 ms

Temporal parsing:
< 3 ms common path

Exact PhraseMatcher:
< 10 ms typical

Context resolution:
< 5 ms

Residual extraction:
< 2 ms

Fuzzy fallback:
0 ms when not needed
bounded when needed

Total local resolver:
p50 < 20 ms
p95 < 50 ms
```

These are engineering targets and must be benchmarked in the actual Lambda runtime.

---

# 47. Lambda Performance Practices

Initialize globally:

```python
NLP = spacy.blank("en")
TAXONOMY = TaxonomyManager(...)
RESOLVER = Resolver(...)
HTTP_CLIENT = httpx.Client(...)
```

Do not recreate these for every invocation.

Use a persistent HTTP client to reuse TCP/TLS connections.

Example:

```python
import httpx


client = httpx.Client(
    timeout=httpx.Timeout(1.5, connect=0.5)
)
```

Then reuse:

```python
client.post(...)
```

for search calls.

---

# 48. Suggested Source Layout

```text
alexa_skill/
│
├── lambda_function.py
│
├── requirements.txt
│
├── resolver/
│   ├── __init__.py
│   ├── engine.py
│   ├── models.py
│   ├── normalize.py
│   ├── command_rules.py
│   ├── temporal.py
│   ├── entity_matcher.py
│   ├── context.py
│   ├── fuzzy.py
│   ├── residual.py
│   └── confidence.py
│
├── taxonomy/
│   ├── manager.py
│   ├── loader.py
│   ├── manifest.py
│   ├── snapshot.py
│   └── static/
│       └── locations.json
│
├── search/
│   ├── client.py
│   └── payload.py
│
└── tests/
    ├── golden_utterances.json
    ├── test_temporal.py
    ├── test_entities.py
    ├── test_context.py
    ├── test_residual.py
    ├── test_taxonomy_refresh.py
    └── test_payloads.py
```

---

# 49. Resolver Skeleton

```python
class Resolver:
    def __init__(self, taxonomy):
        self.taxonomy = taxonomy

    def resolve(
        self,
        utterance: str,
        alexa_user_id: str,
        timezone: str,
    ) -> dict:

        normalized = normalize(utterance)

        command_state = parse_command_modifiers(
            normalized
        )

        temporal = parse_temporal(
            normalized,
            timezone=timezone,
        )

        exact_entities = self.taxonomy.match_exact(
            normalized,
            excluded_spans=temporal.spans,
        )

        resolved_entities = resolve_context(
            normalized,
            exact_entities,
        )

        unresolved_spans = identify_unresolved_candidate_spans(
            normalized,
            temporal,
            resolved_entities,
        )

        fuzzy_entities = self.taxonomy.match_fuzzy(
            normalized,
            unresolved_spans,
        )

        entities = merge_entity_results(
            resolved_entities,
            fuzzy_entities,
        )

        query = extract_residual_query(
            normalized,
            command_state,
            temporal,
            entities,
        )

        plan = build_search_plan(
            alexa_user_id=alexa_user_id,
            query=query,
            command_state=command_state,
            temporal=temporal,
            entities=entities,
        )

        return build_hear_payload(plan)
```

---

# 50. Hear Payload Builder

```python
def build_hear_payload(plan: SearchPlan) -> dict:
    payload = {
        "alexaUserId": plan.alexa_user_id,
        "isLocal": plan.is_local,
        "isRecommended": plan.is_recommended,
        "limit": plan.limit,
        "page": plan.page,
        "query": plan.query,
        "sort": plan.sort,
    }

    filters = {}

    if plan.category_slugs:
        filters["categorySlugs"] = plan.category_slugs

    if plan.creator_ids:
        filters["creatorIds"] = plan.creator_ids

    if plan.organization_ids:
        filters["organizationIds"] = plan.organization_ids

    if plan.publication_ids:
        filters["publicationIds"] = plan.publication_ids

    if plan.tags:
        filters["tags"] = plan.tags

    if plan.city:
        filters["city"] = plan.city

    if plan.country_code:
        filters["countryCode"] = plan.country_code

    if filters:
        payload["filter"] = filters

    return payload
```

---

# 51. Taxonomy Manager Skeleton

```python
class TaxonomyManager:
    def __init__(self, revision_store, remote_loader):
        self.revision_store = revision_store
        self.remote_loader = remote_loader

        self.revision = None
        self.snapshot = None

        self.load_initial_snapshot()

    def refresh_if_needed(self):
        latest = self.revision_store.get_current()

        if latest.revision == self.revision:
            return False

        candidate = self.build_candidate_snapshot(latest)

        candidate.validate()
        candidate.smoke_test()

        self.snapshot = candidate
        self.revision = latest.revision

        return True
```

Actual implementation should protect the atomic swap with a lock if concurrent execution inside the same process is possible.

---

# 52. Taxonomy Snapshot

A compiled snapshot should contain:

```python
class TaxonomySnapshot:
    revision: str

    phrase_matcher: object

    entities_by_rule_id: dict

    creator_aliases: dict
    organization_aliases: dict
    publication_aliases: dict
    category_aliases: dict
    tag_aliases: dict
    location_aliases: dict

    creator_fuzzy_choices: list
    organization_fuzzy_choices: list
    publication_fuzzy_choices: list
    category_fuzzy_choices: list
    tag_fuzzy_choices: list
```

All of these are built once per taxonomy revision.

---

# 53. Webhook Payload

Recommended:

```json
{
  "event": "taxonomy.updated",
  "schemaVersion": 3,
  "revision": "2026-07-29T00:30:00Z-8b3e92",
  "manifestUrl": "https://f003.backblazeb2.com/file/OldAlexa/runtime/taxonomy/v3/manifest.json",
  "changed": [
    "creators.json",
    "aliases.json"
  ]
}
```

The AWS webhook endpoint updates the shared revision record.

It does not perform NLP.

It does not need to wake every Alexa Lambda instance.

---

# 54. Static Location Policy

Locations do not need to be regenerated on every taxonomy build.

Treat them independently.

Possible strategy:

```text
Dynamic taxonomy revision:
2026-07-29-abc

Static location revision:
locations-v1
```

The Lambda package can contain:

```text
locations-v1.json
```

If geographic data changes later:

```text
locations-v2
```

is deployed intentionally.

This keeps dynamic taxonomy refresh fast.

---

# 55. Logging

Every search should produce one structured diagnostic event.

Example:

```json
{
  "utterance": "find me the latest sport track from david",
  "normalized": "find me the latest sport track from david",
  "taxonomyRevision": "2026-07-29T00:30:00Z-8b3e92",
  "entities": [
    {
      "text": "sport",
      "type": "category",
      "value": "sports",
      "method": "alias",
      "confidence": 0.99
    },
    {
      "text": "david",
      "type": "creator",
      "value": "DAVID_UUID",
      "method": "exact",
      "confidence": 0.99
    }
  ],
  "query": "",
  "isLocal": false,
  "isRecommended": false,
  "sort": "latest",
  "timingMs": {
    "taxonomyRevisionCheck": 7,
    "normalize": 1,
    "temporal": 1,
    "entityResolution": 5,
    "payload": 1,
    "backendSearch": 78,
    "total": 93
  }
}
```

This makes it possible to determine whether a wrong result came from:

```text
Alexa transcription
resolver
taxonomy
backend filter construction
Meilisearch ranking
recommendation logic
geo logic
```

---

# 56. Golden Test Dataset

Create:

```text
tests/golden_utterances.json
```

Every record should contain:

```json
{
  "utterance": "find me the latest sport track from david",
  "expected": {
    "query": "",
    "categorySlugs": ["sports"],
    "creator": "David Beard",
    "sort": "latest",
    "isLocal": false,
    "isRecommended": false
  }
}
```

---

# 57. Initial Test Utterances

At minimum test:

```text
play sport

play me sport from monday

play sport on monday

play sport from david

play sport from david beard

find me the latest sport track from david

play sport from david from last week

play david's latest news

give me news about havering council

play something in havering

play havering residents association

play the latest from david

play yesterday's news

play news from last monday

play news about the reservoir from david

play news from david about council tax

play something around lagos about traffic

play local news

play news near me

recommend some news

recommend sports from david

give me something I would like

find politics in lagos

play breaking news

play local politics from HRA

play the latest local news from david

play me football

play soccer news

play david bird
```

Expand this to at least 100 real Alexa-like utterances before production cutover.

Eventually build the dataset from actual anonymized failed searches.

---

# 58. Metrics

Measure resolver and search separately.

Important metrics:

```text
entity precision
entity recall
creator resolution accuracy
organization resolution accuracy
location resolution accuracy
category resolution accuracy
date interpretation accuracy
residual query accuracy
full SearchPlan accuracy
top-1 result accuracy
zero-result rate
wrong-play rate
p50 resolver latency
p95 resolver latency
backend p50
backend p95
total Alexa search p50
total Alexa search p95
```

For Alexa, `wrong-play rate` is particularly important because Alexa normally selects one result instead of showing a result page.

---

# 59. Why Semantic Router Is Not the Primary Solution

Semantic Router can answer:

```text
which general intent does this sentence resemble?
```

That is not the hardest problem here.

The difficult problems are:

```text
Is David a creator?

Which David?

Is HRA an organization?

Is Havering a location or part of an organization name?

Does "from Monday" mean a date filter?

Does "from David" mean a creator?

Should "reservoir" remain in query?

Does "latest" mean sorting rather than search text?

Does "local" mean geo-radius search?
```

Those require taxonomy + context + rules.

Therefore:

```text
Semantic Router:
optional later

spaCy + taxonomy + context rules:
core

RapidFuzz:
fallback

Meilisearch:
retrieval
```

---

# 60. Possible Future Semantic Layer

After the deterministic resolver is stable, a tiny semantic fallback may help categories and tags.

Example:

```text
"soccer"
```

could map to:

```text
football
sports
```

or:

```text
stories about burglaries
```

could map toward:

```text
crime
local crime
```

This must happen only after exact/alias resolution fails.

Do not put embeddings in the critical proper-name path.

---

# 61. Implementation Phases

## Phase 1 — Remove gRPC

Tasks:

```text
remove gRPC client/server path
create local resolver Python package
create Hear API HTTPS client
define SearchPlan
```

Exit condition:

```text
Lambda can send a manually constructed structured payload to Hear backend and receive valid search results.
```

---

## Phase 2 — Exact Resolver

Build:

```text
normalization
command phrase detection
sort modifier detection
spaCy PhraseMatcher
exact taxonomy aliases
residual query extraction
```

Exit condition:

```text
exact creator/category/organization/location tests pass.
```

---

## Phase 3 — Temporal Resolver

Build:

```text
today
yesterday
last week
this week
Monday
from Monday
on Monday
since Monday
last Monday
last month
```

Extend backend payload for date filters.

Exit condition:

```text
date phrases produce the expected timestamps and Meilisearch date constraints.
```

---

## Phase 4 — Context Resolution

Build:

```text
by
from
in
near
around
about
on
since
```

Add:

```text
longest-span resolution
context scoring
entity type preference
```

Exit condition:

```text
"from David" and "from Monday" resolve differently and correctly.
```

---

## Phase 5 — Fuzzy Fallback

Add RapidFuzz.

Only fuzzy:

```text
unresolved spans
against context-scoped entity types
```

Exit condition:

```text
common Alexa ASR mistakes resolve without increasing wrong-creator errors.
```

---

## Phase 6 — Taxonomy Synchronization

Build:

```text
manifest revision
webhook
DynamoDB revision store
changed-file hashes
dynamic downloads
static locations
atomic matcher rebuild
/tmp cache
```

Exit condition:

```text
backend publishes new creator -> webhook fires -> next relevant Lambda request loads new creator -> resolver recognizes it.
```

---

## Phase 7 — Search Quality

Tune:

```text
Meilisearch filters
searchable fields
ranking
latest sorting
recommendations
local search
one zero-result fallback
```

Exit condition:

```text
correct SearchPlan produces correct top-1 Hear result across golden tests.
```

---

## Phase 8 — Performance

Benchmark:

```text
512 MB Lambda
1024 MB Lambda
1536 MB Lambda
```

Measure:

```text
cold start
warm resolver
taxonomy revision read
backend HTTP
Meilisearch
total Alexa latency
```

Exit condition:

```text
resolver p50 < 20 ms
resolver p95 < 50 ms

and end-to-end latency meets the product target.
```

---

# 62. Definition of Done

The new resolver is ready when:

- gRPC is completely removed from the Alexa search path.
- Python resolver runs inside the Alexa Lambda.
- spaCy PhraseMatcher resolves exact taxonomy names and aliases.
- proper-name matching uses stable IDs.
- category matching uses category slugs.
- location matching generates city/country or `isLocal`.
- temporal language is parsed separately.
- context distinguishes `from David` from `from Monday`.
- `latest` controls sorting instead of being sent as query text.
- `recommended` controls personalization.
- `local` controls geo search.
- residual query contains only actual full-text search terms.
- RapidFuzz is used only as a scoped fallback.
- locations are static and are not regenerated during normal taxonomy updates.
- dynamic taxonomy changes propagate through webhook + shared revision.
- Lambda downloads only changed files.
- taxonomy updates are hash checked.
- a bad taxonomy update cannot replace the current working resolver.
- backend remains responsible for Meilisearch.
- all search decisions are logged.
- at least 100 golden Alexa utterances pass before cutover.
- resolver latency is measured at p50 and p95.
- wrong-play rate and zero-result rate are monitored after release.

---

# 63. Final Recommended Request Flow

Example:

```text
USER:
"find me the latest sport track from david"
```

### 1. Normalize

```text
find me the latest sport track from david
```

### 2. Modifiers

```text
find me
    -> command

latest
    -> sort=latest
```

### 3. Taxonomy matching

```text
sport
    -> categorySlugs=["sports"]

david
    -> creatorIds=["DAVID_UUID"]
```

### 4. Context

```text
from david
```

confirms:

```text
David is a creator
```

### 5. Residual extraction

Remove:

```text
find me
latest
sport
track
from
david
```

Residual:

```text
""
```

### 6. Final Hear request

```json
{
  "alexaUserId": "USER_ID",
  "filter": {
    "categorySlugs": [
      "sports"
    ],
    "creatorIds": [
      "DAVID_UUID"
    ]
  },
  "isLocal": false,
  "isRecommended": false,
  "limit": 20,
  "page": 0,
  "query": "",
  "sort": "latest"
}
```

### 7. Backend

The backend converts exact facets into Meilisearch filters and sorts newest first.

### 8. Alexa

Alexa receives the top valid result and begins playback.

---

# 64. Final Architecture Decision

The production direction should be:

```text
Python Alexa Lambda
+
Local spaCy resolver
+
Taxonomy exact aliases
+
Context rules
+
Temporal parser
+
RapidFuzz fallback
+
Static location data
+
Dynamic taxonomy revision/cache
+
HTTPS Hear search endpoint
+
Existing backend Meilisearch
```

Do **not** reintroduce a network NLP resolver.

Do **not** send the whole sentence blindly to Meilisearch.

Do **not** use Semantic Router as the core entity resolver.

Do **not** re-download all taxonomy on every Alexa request.

The resolver's job is to transform natural language into the exact Hear search contract quickly and deterministically.

The backend's job is to execute that structured request efficiently against Meilisearch.
