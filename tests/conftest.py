import os
import tempfile

# Keep test state in a temporary directory.
os.environ["MARKET_DATA_DIR"] = tempfile.mkdtemp(prefix="research-market-tests-")
