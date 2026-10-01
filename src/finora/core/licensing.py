from enum import Enum

class Edition(str, Enum):
    FREE = "free"
    PLUS = "plus"
    PRO = "pro"

FEATURES = {
    Edition.FREE: {"accounts_max": 3, "ofx": False, "attachments": False, "budget": False, "multi_currency": False, "entities_max": 1},
    Edition.PLUS: {"accounts_max": None, "ofx": True, "attachments": True, "budget": True, "multi_currency": False, "entities_max": 1},
    Edition.PRO:  {"accounts_max": None, "ofx": True, "attachments": True, "budget": True, "multi_currency": True, "entities_max": None},
}

def allowed(edition: Edition, feature: str):
    return FEATURES[edition].get(feature)
