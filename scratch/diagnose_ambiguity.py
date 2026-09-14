import sys
sys.path.insert(0, "c:/Users/USER/Downloads/hear-py")

from src.models.dialog import DialogSelection
from src.constants.discovery import DiscoveryConstants

pending = {
    "phrase": "Pendle Voice",
    "candidates": [
        {"id": "p1", "name": "Dalesman", "entityType": "publication"},
        {"id": "p2", "name": "Lancashire Life", "entityType": "publication"},
        {"id": "p3", "name": "Leader and Times", "entityType": "publication"},
    ],
    "expiresAt": 9999999999,
}

print("Displayed choices:", DialogSelection.displayed_choices(pending))
raw_key = DialogSelection._selection_text("second")
print("raw_key:", repr(raw_key))
print("ordinal in ORDINAL_INDEX:", DiscoveryConstants.ORDINAL_INDEX.get(raw_key))
print("Match pending candidate for 'second':", DialogSelection.match_pending_candidate(None, pending, "second"))
