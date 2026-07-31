# Hear content-search simulation report

Generated: 2026-07-31T14:47:59.967536+00:00
Corpus: 256 simulated utterances from `en-GB.json`
Fixture taxonomy: `tests\fixtures\taxonomy`

## Status counts

| Status | Count |
| --- | --- |
| ambiguous | 3 |
| category | 143 |
| city | 44 |
| creator | 8 |
| empty | 3 |
| local | 24 |
| org | 19 |
| query | 8 |
| recommended | 4 |

## By intent

| Intent | Utterances | Statuses |
| --- | --- | --- |
| PlayContentIntent | 132 | category, empty |
| PlayLocalIntent | 48 | city, local |
| PlayRecommendationIntent | 6 | category, recommended |
| PlayByOrganizationIntent | 6 | org |
| PlayByCreatorIntent | 8 | creator |
| WhatsTrendingIntent | 12 | category |
| TownCaptureIntent | 12 | city, org |
| SetLocationIntent | 12 | city, org |
| ClarifySelectionIntent | 12 | ambiguous, org |
| BrowseContentIntent | 5 | query |
| ShowMoreBrowseIntent | 3 | query |

## Sample resolutions

| Intent | Utterance | Category | Query | City | Local | Recommended | Sort | Orgs | Creators |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PlayContentIntent | play me something about news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play something about news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | give me some news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play recent news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | get me the latest news | news | get me | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play latest news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me latest news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | give me news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me some news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the newest news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me something on news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the latest news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me the latest news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | find me news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | find something about news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me recent news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | put on some news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me the newest news | news | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play some news | news | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me something about sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play something about sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | give me some sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play recent sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | get me the latest sport | sport | get me | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play latest sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me latest sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | give me sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me some sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the newest sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me something on sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the latest sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me the latest sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | find me sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | find something about sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me recent sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | put on some sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me the newest sport | sport | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play some sport | sport | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me something about politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play something about politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | give me some politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play recent politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | get me the latest politics | politics | get me | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play latest politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me latest politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | give me politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me some politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the newest politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me something on politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the latest politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me the latest politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | find me politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | find something about politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me recent politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | put on some politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me the newest politics | politics | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play some politics | politics | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me something about technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play something about technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | give me some technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play recent technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | get me the latest technology | technology | get me | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play latest technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me latest technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | give me technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me some technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the newest technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me something on technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the latest technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me the latest technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | find me technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | find something about technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me recent technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | put on some technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me the newest technology | technology | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play some technology | technology | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me something about business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play something about business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | give me some business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play recent business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | get me the latest business | business | get me | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play latest business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me latest business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | give me business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me some business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the newest business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me something on business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the latest business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me the latest business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | find me business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | find something about business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me recent business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | put on some business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me the newest business | business | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play some business | business | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me something about health | health | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play something about health | health | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | give me some health | health | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play recent health | health | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | get me the latest health | health | get me | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play health | health | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play latest health | health | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me latest health | health | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | give me health | health | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play me some health | health | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the newest health | health | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me something on health | health | - | - | False | False | relevance | 0 | 0 |
| PlayContentIntent | play the latest health | health | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | play me the latest health | health | - | - | False | False | latest | 0 | 0 |
| PlayContentIntent | find me health | health | - | - | False | False | relevance | 0 | 0 |