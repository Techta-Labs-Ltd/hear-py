# Development Error Register

This register records the development incidents observed on 2026-09-16. It distinguishes the Alexa request path from the independent outbound-event and notification HTTP paths.

| Observed error | Affected path | Root cause | Status |
| --- | --- | --- | --- |
| `EssentialPersistenceError` and Alexa `INVALID_RESPONSE` | Every request that needed a durable save, including `AudioPlayer.PlaybackStarted`, `PlaybackNearlyFinished`, and `LaunchRequest` | DynamoDB rejected `TransactWriteItems` with `ValidationException: ExpressionAttributeValues must not be empty`. The outbox `Put` operation sent an empty `ExpressionAttributeValues` object for an `attribute_not_exists` condition. | Fixed in code: omit the parameter when the condition has no values. Regression test added. |
| Playback stopped after the first queued item | AudioPlayer queue progression | The failed state transaction prevented the active queue and the next-item event from being committed. Alexa therefore received no valid `ENQUEUE` response to `PlaybackNearlyFinished`. | Expected to resolve with the persistence fix; validate with a fresh multi-item playback after deployment. |
| `System.ExceptionEncountered errorType=INVALID_RESPONSE` | Alexa to Lambda request response | A consequence of `EssentialPersistenceError` escaping the response interceptor, rather than an Alexa endpoint or skill-ID problem. | Resolves when the transaction succeeds. |
| `notification API rejected operation=fetch status=404` | Lambda to Hear notification API | This is a separate inbound-notification fetch path: `<HEAR_API_URL>/<HEAR_API_PATH_PREFIX>/notification`. It does not use the outbound event webhook. The development API currently returns 404 for that notification endpoint. | Open backend contract/configuration issue; it does not cause the Alexa invalid response. |
| Old outbound event URL `/api/v1/alexa/events` | Outbound worker Lambda to Hear backend webhook | The configured target was a legacy route. | Fixed and deployed: `https://alexa.hear.media/api/v1/webhooks/event`. |

## Verification evidence

- The development Lambda execution role is allowed to call `dynamodb:TransactWriteItems` on the listener-state table.
- The development Lambda is configured with the corrected webhook URL.
- The sampled X-Ray trace for request `02b2d986-c3ba-4417-8205-3584f99e88e1` identified the DynamoDB validation error above.

## Guardrail

For DynamoDB expression conditions such as `attribute_not_exists`, include `ExpressionAttributeValues` only when the generated condition actually has values. AWS rejects an explicitly supplied empty object.