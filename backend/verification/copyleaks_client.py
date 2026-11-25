
import os
from dotenv import load_dotenv

# Load settings from the project's .env file
load_dotenv()

COPYLEAKS_EMAIL = os.getenv("COPYLEAKS_EMAIL", "")
COPYLEAKS_API_KEY = os.getenv("COPYLEAKS_API_KEY", "")
COPYLEAKS_SANDBOX = os.getenv("COPYLEAKS_SANDBOX", "true").lower() == "true"


def is_copyleaks_configured():
    """Check whether Copyleaks credentials are available."""
    return bool(COPYLEAKS_EMAIL and COPYLEAKS_API_KEY)


def get_copyleaks_status():
    """Return the current integration status."""
    if is_copyleaks_configured():
        return {
            "configured": True,
            "sandbox": COPYLEAKS_SANDBOX,
            "message": "Copyleaks credentials are available."
        }

    return {
        "configured": False,
        "sandbox": COPYLEAKS_SANDBOX,
        "message": "Copyleaks is not configured. Add credentials to .env."
    }
