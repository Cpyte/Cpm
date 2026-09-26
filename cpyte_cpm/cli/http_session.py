"""HTTP session management for CPM.

Provides a shared requests.Session with connection pooling for faster
metadata fetching and package downloads.
"""

import requests as rq
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Global session instance
_session: rq.Session | None = None


def get_session() -> rq.Session:
    """Get or create a shared HTTP session with connection pooling.

    Features:
        - Connection pooling (reuse TCP connections)
        - Automatic retries on transient failures
        - Keep-alive for persistent connections
    """
    global _session
    if _session is None:
        _session = rq.Session()

        # Configure connection pooling
        adapter = HTTPAdapter(
            pool_connections=10,  # Number of connection pools
            pool_maxsize=10,  # Max connections per pool
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
            ),
        )
        _session.mount("http://", adapter)
        _session.mount("https://", adapter)

        # Set default headers for better performance
        _session.headers.update(
            {
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }
        )

    return _session


def close_session():
    """Close the shared HTTP session."""
    global _session
    if _session is not None:
        _session.close()
        _session = None
