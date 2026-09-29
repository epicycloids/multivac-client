import os
import tempfile

# Tests own a separate local state directory and never modify demonstration data.
os.environ["MARKET_DATA_DIR"] = tempfile.mkdtemp(prefix="research-market-tests-")
