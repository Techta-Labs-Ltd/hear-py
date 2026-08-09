# Alexa permission configuration

The Lambda response can request consent only for permissions enabled in the
Alexa developer console for the same skill and stage.

For development skill `amzn1.ask.skill.502ef74e-db9f-485f-acdd-13d23c895e59`:

1. Open **Build → Permissions** in the Alexa developer console.
2. Enable **Device Address → Full Address**.
3. Build the skill model and enable the development skill on the test account.
4. Say yes to Hear's location-permission question.
5. Open the Alexa app Activity screen, or use a supported screened device, and
   approve the `AskForPermissionsConsent` card.
6. Reopen Hear. The next request re-checks the granted scope and fetches the
   device address. A voice-only Echo does not display a visual card.

The requested runtime scope is:

`read::alexa:device:all:address`

Do not enable or request Geolocation until a feature directly consumes live
coordinates. Permission approval happens outside the Alexa voice session, so
the backend must not wait for `Connections.Response`.

Standard-card images must be licensed HTTPS JPEG or PNG assets. The response
builder rejects other URL schemes and extensions; the content service remains
responsible for supplying the recommended 720x480 and 1200x800 variants and
keeping each asset below 500 KB.
