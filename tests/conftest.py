# ABOUTME: Shared pytest configuration and fixtures.
# ABOUTME: Loads .env before test collection so skip markers see env vars.

from dotenv import load_dotenv

# Load .env early so pytest.mark.skipif conditions on env vars (e.g. MASSIVE_API_KEY)
# are evaluated with the correct values at collection time.
load_dotenv()
