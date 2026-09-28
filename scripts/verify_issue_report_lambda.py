from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


class IssueReportLambdaVerifier:
    def __init__(self, function_name: str, table_name: str, skill_id: str, region: str) -> None:
        self.function_name = function_name
        self.skill_id = skill_id
        self.lambda_client = boto3.client("lambda", region_name=region)
        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.prefix = (
            "amzn1.ask.account.ISSUE_REPORT_"
            + str(int(time.time()))
            + "_"
            + uuid.uuid4().hex[:8]
        )
        self.users: set[str] = set()
        self.failures: list[str] = []

    def user(self, label: str) -> str:
        value = f"{self.prefix}_{label.upper()}"
        self.users.add(value)
        return value

    def clear_user(self, user_id: str) -> None:
        response = self.table.query(
            KeyConditionExpression=Key("id").eq(user_id),
            ConsistentRead=True,
        )
        with self.table.batch_writer() as batch:
            for item in response.get("Items") or []:
                batch.delete_item(Key={"id": item["id"], "scope": item["scope"]})

    def cleanup(self) -> None:
        for user_id in self.users:
            try:
                self.clear_user(user_id)
            except Exception as exc:
                print(f"WARN cleanup {user_id}: {type(exc).__name__}")

    def seed(self, user_id: str, scope: str, attributes: dict[str, Any]) -> None:
        self.clear_user(user_id)
        self.table.put_item(
            Item={
                "id": user_id,
                "scope": scope,
                "schemaVersion": 2,
                "stateVersion": 1,
                "expiresAt": int(time.time()) + 3600,
                "attributes": attributes,
            }
        )

    def add_scope(self, user_id: str, scope: str, attributes: dict[str, Any]) -> None:
        self.table.put_item(
            Item={
                "id": user_id,
                "scope": scope,
                "schemaVersion": 2,
                "stateVersion": 1,
                "expiresAt": int(time.time()) + 3600,
                "attributes": attributes,
            }
        )

    def read_scope(self, user_id: str, scope: str) -> dict[str, Any]:
        item = self.table.get_item(
            Key={"id": user_id, "scope": scope},
            ConsistentRead=True,
        ).get("Item") or {}
        attributes = item.get("attributes")
        return attributes if isinstance(attributes, dict) else {}

    def envelope(
        self,
        user_id: str,
        request: dict[str, Any],
        *,
        audio_player: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        suffix = uuid.uuid4().hex
        return {
            "version": "1.0",
            "session": {
                "new": False,
                "sessionId": f"amzn1.echo-api.session.issue-report-{suffix}",
                "application": {"applicationId": self.skill_id},
                "attributes": {"onboardingComplete": True},
                "user": {"userId": user_id},
            },
            "context": {
                "System": {
                    "application": {"applicationId": self.skill_id},
                    "user": {
                        "userId": user_id,
                        "permissions": {"scopes": {}},
                    },
                    "device": {
                        "deviceId": f"amzn1.ask.device.issue-report-{suffix}",
                        "supportedInterfaces": {"AudioPlayer": {}},
                    },
                    "apiEndpoint": "https://api.amazonalexa.com",
                    "apiAccessToken": "issue-report-smoke-token",
                },
                "AudioPlayer": audio_player or {"playerActivity": "IDLE"},
            },
            "request": {
                "requestId": f"amzn1.echo-api.request.issue-report-{suffix}",
                "timestamp": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "locale": "en-GB",
                **request,
            },
        }

    def invoke(
        self,
        user_id: str,
        request: dict[str, Any],
        *,
        audio_player: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.lambda_client.invoke(
            FunctionName=self.function_name,
            InvocationType="RequestResponse",
            LogType="Tail",
            Payload=json.dumps(
                self.envelope(user_id, request, audio_player=audio_player),
                separators=(",", ":"),
            ).encode(),
        )
        if result.get("FunctionError"):
            raise AssertionError(f"Lambda FunctionError={result['FunctionError']}")
        raw = result["Payload"].read()
        response = json.loads(raw) if raw else {}
        if not isinstance(response, dict) or response.get("version") != "1.0":
            raise AssertionError(f"Invalid Alexa response: {response!r}")
        return response

    @staticmethod
    def speech(response: dict[str, Any]) -> str:
        output = (response.get("response") or {}).get("outputSpeech") or {}
        return str(output.get("ssml") or output.get("text") or "")

    def run(self, name: str, callback) -> None:
        try:
            detail = callback()
            print(f"PASS lambda: {name}" + (f" -> {detail}" if detail else ""))
        except Exception as exc:
            self.failures.append(name)
            print(f"FAIL lambda: {name} -> {type(exc).__name__}: {exc}")

    def verify_idle_speed(self, direction: str, expected: str) -> str:
        user_id = self.user(f"idle-{direction}")
        self.clear_user(user_id)
        response = self.invoke(
            user_id,
            {
                "type": "IntentRequest",
                "intent": {
                    "name": "IncreaseSpeedIntent"
                    if direction == "up"
                    else "DecreaseSpeedIntent",
                    "confirmationStatus": "NONE",
                    "slots": {},
                },
            },
        )
        speech = self.speech(response)
        if expected not in speech:
            raise AssertionError(f"expected {expected!r}, got {speech!r}")
        if "does not have faster or slower versions" in speech:
            raise AssertionError("old unsupported-recording message returned while idle")
        return speech

    def verify_active_invalid_speed_continues(self) -> str:
        user_id = self.user("active-invalid-speed")
        audio_url = "https://cdn.hear.media/issue-report-active.mp3"
        self.seed(
            user_id,
            "PLAYBACK",
            {
                "activePlayback": {
                    "contentId": "issue-report-active",
                    "token": "issue-report-active",
                    "title": "Track__001",
                    "organizationName": "Sound On",
                    "audioUrl": audio_url,
                    "durationMs": 180000,
                    "offsetMs": 42000,
                    "listenedMs": 42000,
                    "status": "playing",
                    "startedAt": 1,
                    "updatedAt": 1,
                    "playbackSpeeds": [
                        {"speed": "1", "audioUrl": audio_url},
                        {
                            "speed": "1.25",
                            "audioUrl": "https://cdn.hear.media/issue-report-active-1-25.mp3",
                        },
                    ],
                },
                "currentPlaybackSpeeds": [
                    {"speed": "1", "audioUrl": audio_url},
                    {
                        "speed": "1.25",
                        "audioUrl": "https://cdn.hear.media/issue-report-active-1-25.mp3",
                    },
                ],
            },
        )
        response = self.invoke(
            user_id,
            {
                "type": "IntentRequest",
                "intent": {
                    "name": "SetPlaybackSpeedIntent",
                    "confirmationStatus": "NONE",
                    "slots": {
                        "speed": {
                            "name": "speed",
                            "value": "sixth",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
            audio_player={
                "playerActivity": "PLAYING",
                "token": "issue-report-active",
                "offsetInMilliseconds": 42000,
            },
        )
        speech = self.speech(response)
        directives = (response.get("response") or {}).get("directives") or []
        if "first through fifth speed" not in speech:
            raise AssertionError(f"speed guidance missing: {speech!r}")
        if not any(
            isinstance(item, dict) and item.get("type") == "AudioPlayer.Play"
            for item in directives
        ):
            raise AssertionError(f"active audio was not continued: {directives!r}")
        if "what would you like to listen to today" in speech.lower():
            raise AssertionError("fell through to generic discovery")
        return speech

    def verify_feedback_source(self) -> str:
        user_id = self.user("feedback-source")
        self.seed(
            user_id,
            "DIALOG",
            {
                "awaitingFeedback": True,
                "pendingFeedback": {
                    "feedbackKey": "content-feedback",
                    "subjectType": "content",
                    "contentId": "content-feedback",
                    "title": "Track__001",
                    "organizationId": "org-sound-on",
                    "organizationName": "Sound On",
                    "completed": True,
                    "createdAt": int(time.time() * 1000),
                },
            },
        )
        response = self.invoke(
            user_id,
            {
                "type": "IntentRequest",
                "intent": {
                    "name": "FeedbackResponseIntent",
                    "confirmationStatus": "NONE",
                    "slots": {},
                },
            },
        )
        speech = self.speech(response)
        if "Sound On" not in speech:
            raise AssertionError(f"organization missing from feedback prompt: {speech!r}")
        if "Track__001" in speech:
            raise AssertionError(f"internal track title leaked: {speech!r}")
        if "I enjoyed it" not in speech:
            raise AssertionError(f"new feedback wording missing: {speech!r}")
        return speech

    def verify_publication_end_wording(self) -> str:
        user_id = self.user("publication-end")
        self.seed(
            user_id,
            "PLAYBACK",
            {
                "playbackQueue": {
                    "queueId": "queue-publication-end",
                    "source": "publication",
                    "publicationId": "publication-1",
                    "publicationTitle": "The Gazette",
                    "orderedContentIds": ["content-1"],
                    "currentIndex": 0,
                    "createdAt": int(time.time() * 1000),
                    "discoveryContext": {
                        "kind": "publication",
                        "name": "The Gazette",
                    },
                }
            },
        )
        response = self.invoke(
            user_id,
            {
                "type": "IntentRequest",
                "intent": {
                    "name": "AMAZON.NextIntent",
                    "confirmationStatus": "NONE",
                    "slots": {},
                },
            },
        )
        speech = self.speech(response)
        if "You've reached the end of this episode." not in speech:
            raise AssertionError(f"episode end wording missing: {speech!r}")
        return speech

    def verify_finished_state(self) -> str:
        user_id = self.user("playback-finished")
        self.seed(
            user_id,
            "PLAYBACK",
            {
                "activePlayback": {
                    "contentId": "content-finished",
                    "token": "content-finished",
                    "title": "Track__001",
                    "organizationName": "Sound On",
                    "audioUrl": "https://cdn.hear.media/content-finished.mp3",
                    "durationMs": 60000,
                    "offsetMs": 59000,
                    "listenedMs": 59000,
                    "status": "playing",
                    "startedAt": 1,
                    "updatedAt": 1,
                }
            },
        )
        self.invoke(
            user_id,
            {
                "type": "AudioPlayer.PlaybackFinished",
                "token": "content-finished",
                "offsetInMilliseconds": 60000,
            },
        )
        state = self.read_scope(user_id, "PLAYBACK").get("activePlayback") or {}
        if state.get("status") != "completed":
            raise AssertionError(f"expected completed state, got {state!r}")
        return f"status={state.get('status')}"

    def verify_ambiguity_number_one(self) -> str:
        user_id = self.user("ambiguity-number-one")
        expires_at = int(time.time()) + 3600
        candidates = [
            {
                "type": "organization",
                "id": "swindon-1",
                "name": "Swindon Talking News",
            },
            {
                "type": "organization",
                "id": "swindon-2",
                "name": "Swindon Audio News",
            },
        ]
        pending = {
            "intent": "search",
            "searchPayload": {"query": "", "filter": {}},
            "slots": {},
            "candidates": candidates,
            "choiceCandidates": candidates,
            "displayedCandidates": candidates,
            "expiresAt": expires_at,
        }
        self.seed(
            user_id,
            "DIALOG",
            {
                "pendingAmbiguity": pending,
                "activeDialog": {
                    "type": "ambiguity",
                    "context": pending,
                    "expiresAt": expires_at,
                },
            },
        )
        response = self.invoke(
            user_id,
            {
                "type": "IntentRequest",
                "intent": {
                    "name": "ClarifySelectionIntent",
                    "confirmationStatus": "NONE",
                    "slots": {
                        "selection": {
                            "name": "selection",
                            "value": "number 1",
                            "confirmationStatus": "NONE",
                        }
                    },
                },
            },
        )
        speech = self.speech(response)
        dialog = self.read_scope(user_id, "DIALOG")
        remaining = dialog.get("pendingAmbiguity")
        if isinstance(remaining, dict):
            names = [
                str(item.get("name") or "")
                for item in remaining.get("candidates") or []
                if isinstance(item, dict)
            ]
            if "Swindon Talking News" in names and "Swindon Audio News" in names:
                raise AssertionError(
                    f"number 1 did not consume the ambiguity; speech={speech!r}"
                )
        return speech or "ambiguity consumed"

    def verify(self) -> None:
        try:
            self.run(
                "idle increase speed",
                lambda: self.verify_idle_speed("up", "Playback speed set to 1.25x."),
            )
            self.run(
                "idle decrease speed",
                lambda: self.verify_idle_speed("down", "Playback speed set to 0.75x."),
            )
            self.run(
                "active invalid speed keeps playback context",
                self.verify_active_invalid_speed_continues,
            )
            self.run(
                "feedback prefers organization and says I enjoyed it",
                self.verify_feedback_source,
            )
            self.run(
                "publication end says episode",
                self.verify_publication_end_wording,
            )
            self.run(
                "PlaybackFinished persists completed",
                self.verify_finished_state,
            )
            self.run(
                "number 1 consumes ambiguity",
                self.verify_ambiguity_number_one,
            )
        finally:
            self.cleanup()

        print(f"Lambda issue-report failures={len(self.failures)}")
        if self.failures:
            raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--table-name", required=True)
    parser.add_argument("--skill-id", required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    IssueReportLambdaVerifier(
        args.function_name,
        args.table_name,
        args.skill_id,
        args.region,
    ).verify()


if __name__ == "__main__":
    main()
