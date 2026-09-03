# Alexa permission configuration

The Lambda can request only permissions enabled for the same Alexa skill and
stage. These are Alexa capability permissions; Hear does not use account
linking or a Hear OAuth flow.

## Location and profile permissions

For development skill `amzn1.ask.skill.502ef74e-db9f-485f-acdd-13d23c895e59`:

1. Open **Build > Permissions** in the Alexa developer console.
2. Enable **Device Address > Full Address**.
3. Build the skill model and enable the development skill on the test account.
4. Say yes to Hear's location-permission question.
5. Approve the `AskForPermissionsConsent` request in the Alexa app Activity
   screen or on a supported screened device.
6. Reopen Hear. The next request re-checks the scope and fetches the device
   address before asking the listener to confirm the city.

The Device Settings API can return `204 No Content` after consent if the
specific Echo has no address. Set it under **Alexa app > Devices > Echo & Alexa
> Device Location**, then relaunch Hear. Hear falls back to spoken city entry.

If a permission request is not visible in Activity, use **More > Skills & Games
> Your Skills > Dev > test development > Settings > Manage Permissions**.
The backend must not claim delivery merely because the Lambda returned a
consent directive.

The current full-address runtime scope is:

`read::alexa:device:all:address`

Do not enable Geolocation until a feature directly consumes live coordinates.

## Notification permission and proactive events

Enable the Alexa Notifications permission and publish
`AMAZON.MediaContent.Available` in the skill manifest:

~~~json
{
  "permissions": [
    {"name": "alexa::devices:all:notifications:write"}
  ],
  "events": {
    "publications": [
      {"eventName": "AMAZON.MediaContent.Available"}
    ]
  }
}
~~~

The interaction model includes `EnableNotificationsIntent`,
`DisableNotificationsIntent`, and `HearNotificationsIntent`. A listener can say
"enable updates", "turn off updates", or "what are my updates?" Enabling uses
the voice-forward `AskForPermissionsConsent/2` flow. The backend receives
`notifications.enabled` or `notifications.disabled` and owns the durable
preference; the listener-state table does not store it.

Create Login with Amazon security-profile credentials for each environment and
configure:

- development SSM parameters
  `/hear/development/ALEXA_PROACTIVE_CLIENT_ID` and
  `/hear/development/ALEXA_PROACTIVE_CLIENT_SECRET`;
- production GitHub environment secrets
  `ALEXA_PROACTIVE_CLIENT_ID_PROD` and
  `ALEXA_PROACTIVE_CLIENT_SECRET_PROD`.

The backend writes eligible rows directly to `HearNotificationInboxTable`.
Its stream invokes the proactive worker, while the main skill reads the same
inbox on launch or when the listener asks for updates. Full row and event
contracts are in [backend-events-and-feedback.md](backend-events-and-feedback.md).

## Card assets

Standard-card images must be licensed HTTPS JPEG or PNG assets. The response
builder rejects other URL schemes and extensions; the content service remains
responsible for 720x480 and 1200x800 variants below 500 KB.
