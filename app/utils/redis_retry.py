"""Reconnect settings shared by the long-lived Redis clients."""

import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry


def reconnect_on_drop() -> dict:
    """Client kwargs that retry a command once the pool hands out a dead connection.

    A pooled connection the network dropped (idle NAT/conntrack expiry, Redis
    restart) fails its next command with ConnectionError; without a retry that
    surfaces as a 500 from Flask-Session's open_session. Only ConnectionError is
    retried: a hung Redis must still fail within socket_timeout. Retry's default
    supported_errors include timeouts, and the connect and health-check paths
    honour them regardless of retry_on_error, so they are narrowed here too.
    """
    return {
        "retry": Retry(ExponentialBackoff(cap=0.5, base=0.05), 2, supported_errors=(redis.ConnectionError,)),
        "retry_on_error": [redis.ConnectionError],
    }
