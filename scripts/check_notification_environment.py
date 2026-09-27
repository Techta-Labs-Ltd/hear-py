"""Validate deployed Alexa endpoints without displaying secrets."""
from __future__ import annotations

import argparse
import os
from urllib.parse import urlparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    environment = parser.parse_args().environment
    expected = "alexa.hear.surf" if environment == "development" else "alexa.hear.media"
    for key in ("HEAR_API_URL", "WEBHOOK_OUTBOUND_URL"):
        endpoint = urlparse(os.getenv(key, ""))
        if endpoint.scheme != "https" or endpoint.hostname != expected:
            raise SystemExit(f"{key} must use the verified {environment} Alexa hostname")
    print(f"{environment} Alexa endpoints match the verified environment")


if __name__ == "__main__":
    main()
