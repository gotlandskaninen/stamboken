"""
Cache invalidation for genetics data.

Coordinates snapshot rebuilds across gunicorn workers using Redis pub/sub,
debounced recomputation via Redis keys + APScheduler polling, and a leader
poller on the global genetics version. Memoized results are keyed on the
content of the snapshot they were computed from, so nothing is ever deleted:
changed inputs simply miss the cache, and unchanged ones keep hitting it.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import redis

from utils.database import Breeding, Herd
from utils.database import Individual as DBIndividual
from utils.redis_retry import reconnect_on_drop

logger = logging.getLogger("herdbook.cache")

# Redis client — initialized by init_redis()
_redis_client: redis.Redis | None = None
_redis_url: str | None = None  # Stored for creating pub/sub client

PUBSUB_CHANNEL = "herdbook:cache:invalidate"
DEBOUNCE_DELAY_SECONDS = 30
BUILD_WAIT_SECONDS = 300  # a large pedigree's snapshot build can outlast the debounce

# Warm-ups run here, never in the 5 s scheduler job: one waits up to BUILD_WAIT_SECONDS for a build.
_warm_up_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="genetics-warm-up")
_warm_up_queued = {}  # genebank_id -> Future of its latest warm-up
_warm_up_lock = threading.Lock()

# Memoized function references — set by set_cache_and_functions()
_memoized_functions: list = []
_breeding_suggestions_func = None

# genetics_service reference — set lazily to avoid circular import
genetics_service = None

# Last genetics version seen by the leader's poller
_last_seen_version = None


def init_redis(redis_url: str) -> redis.Redis:
    """Initialize the Redis client."""
    global _redis_client, _redis_url
    _redis_url = redis_url
    _redis_client = redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
        **reconnect_on_drop(),
    )
    return _redis_client


def set_cache_and_functions(memoized_funcs, breeding_suggestions_func):
    """Called from herdbook.py to provide the memoized wrappers for the debounced warm-up."""
    global _memoized_functions, _breeding_suggestions_func
    _memoized_functions = memoized_funcs
    _breeding_suggestions_func = breeding_suggestions_func


def get_genebank_ids_for_individual(individual_id: int) -> set[int]:
    """Resolve genebank ID(s) for an individual."""
    try:
        ind = DBIndividual.get_by_id(individual_id)
        herd = ind.origin_herd
        if herd and herd.genebank:
            return {herd.genebank.id}
    except Exception:
        logger.warning(f"Could not resolve genebank for individual {individual_id}")
    return set()


def get_genebank_ids_for_breeding(breeding_id: int) -> set[int]:
    """Resolve genebank ID(s) for a breeding event."""
    try:
        breeding = Breeding.get_by_id(breeding_id)
        herd = breeding.breeding_herd_id
        if herd and herd.genebank:
            return {herd.genebank.id}
    except Exception:
        logger.warning(f"Could not resolve genebank for breeding {breeding_id}")
    return set()


def get_genebank_id_for_herd(herd_code: str) -> set[int]:
    """Resolve genebank ID from a herd code string."""
    try:
        herd = Herd.get(Herd.herd == herd_code)
        if herd.genebank:
            return {herd.genebank_id}
    except Exception:
        logger.warning(f"Could not resolve genebank for herd {herd_code}")
    return set()


def get_genebank_id_for_herd_id(herd_id: int) -> set[int]:
    """Resolve genebank ID from a herd database ID."""
    try:
        herd = Herd.get_by_id(herd_id)
        if herd.genebank:
            return {herd.genebank_id}
    except Exception:
        logger.warning(f"Could not resolve genebank for herd ID {herd_id}")
    return set()


def trigger_invalidation(genebank_id: int):
    """
    Tell every worker to rebuild a genebank's snapshot, and schedule a debounced warm-up.

    Nothing is deleted: memoized results are keyed on their snapshot, so the
    next genetics version misses the cache on its own.

    Steps:
    1. Publish to pub/sub — every worker schedules a background rebuild
    2. Record debounce intent in Redis
    """
    if _redis_client is None:
        logger.warning("Redis not available, skipping cache invalidation")
        return

    try:
        _redis_client.publish(PUBSUB_CHANNEL, str(genebank_id))
        _redis_client.set(
            f"debounce:{genebank_id}",
            int(time.time()),
            ex=120,  # expire after 2min as safety
        )
        logger.info(f"Cache invalidation triggered for genebank {genebank_id}")

    except redis.RedisError as e:
        logger.error(f"Redis error during cache invalidation: {e}")


def _get_genetics_service():
    """Lazy import to avoid circular dependency."""
    global genetics_service
    if genetics_service is None:
        from utils import genetics_service as gs

        genetics_service = gs
    return genetics_service


def _handle_invalidation_message(data: str):
    """Process a single invalidation message from pub/sub."""
    try:
        genebank_id = int(data)
    except (ValueError, TypeError):
        logger.warning(f"Invalid invalidation message: {data}")
        return

    gs = _get_genetics_service()
    try:
        gs.invalidate_cache(genebank_id)
    finally:
        # The listener thread reads the snapshot key; it must not keep a connection open.
        gs.ps._close_db_connection()  # pylint: disable=protected-access
    logger.debug(f"Processed invalidation for genebank {genebank_id}")


def start_pubsub_listener():
    """
    Start a daemon thread that listens for cache invalidation messages.

    Call this once per worker during app initialization.
    Uses a dedicated Redis client WITHOUT socket_timeout so the blocking
    listen() call doesn't time out every 2 seconds.
    """
    if _redis_client is None or _redis_url is None:
        logger.warning("Redis not available, pub/sub listener not started")
        return

    def _listener_loop():
        backoff = 1
        while True:
            try:
                # Dedicated client for pub/sub — no socket_timeout
                # so listen() blocks indefinitely waiting for messages
                pubsub_client = redis.Redis.from_url(
                    _redis_url,
                    socket_connect_timeout=5,
                    decode_responses=True,
                )
                pubsub = pubsub_client.pubsub()
                pubsub.subscribe(PUBSUB_CHANNEL)
                logger.info("Pub/sub listener connected")
                backoff = 1  # reset on successful connect

                for message in pubsub.listen():
                    if message["type"] == "message":
                        _handle_invalidation_message(message["data"])

            except redis.RedisError as e:
                logger.warning(f"Pub/sub connection lost: {e}, reconnecting in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
            except Exception as e:
                logger.error(f"Unexpected error in pub/sub listener: {e}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    thread = threading.Thread(target=_listener_loop, daemon=True, name="cache-invalidation-listener")
    thread.start()
    logger.info("Cache invalidation pub/sub listener thread started")


def _recompute_genebank(genebank_id: int):
    """Eagerly recompute all memoized metrics for a genebank.

    Uses the function references injected via set_cache_and_functions()
    instead of importing from herdbook to avoid circular imports. Waits for
    a snapshot of the latest write first: warming the retained snapshot would
    only hit its own memo and leave the new inputs to the first request.
    """
    logger.info(f"Debounce firing: recomputing metrics for genebank {genebank_id}")
    gs = _get_genetics_service()
    deadline = time.monotonic() + BUILD_WAIT_SECONDS
    snap = None
    try:
        # A write during the running build needs one more; a failing build must not spin.
        for _ in range(3):
            # Starts the build a moved key (or a cold start) needs, and never waits on it untimed.
            snap, stale = gs.snapshot_status(genebank_id, wait=False)
            if snap is not None and not stale:
                break
            gs.ps.wait_for_builds(genebank_id, timeout=max(deadline - time.monotonic(), 0))
        else:
            snap = gs.snapshot_status(genebank_id, wait=False)[0]
    except Exception:  # pylint: disable=broad-except
        logger.warning("Snapshot build for genebank %s not done; warming the current one", genebank_id, exc_info=True)
    if snap is None:
        # Still cold: the bodies would wait on that build untimed and hold up the next genebank.
        logger.warning("No snapshot of genebank %s within the budget; its warm-up is skipped", genebank_id)
        return

    for func in _memoized_functions:
        try:
            func(genebank_id)
        except Exception as e:
            logger.warning(f"Failed to recompute {func.__name__} for genebank {genebank_id}: {e}")

    if _breeding_suggestions_func is not None:
        try:
            _breeding_suggestions_func(genebank_id)
        except Exception as e:
            logger.warning(f"Failed to recompute breeding suggestions for genebank {genebank_id}: {e}")


def _warm_up_quietly(genebank_id):
    try:
        _recompute_genebank(genebank_id)
    except Exception:  # pylint: disable=broad-except
        logger.exception("Genetics warm-up failed for genebank %s", genebank_id)
    finally:
        _get_genetics_service().ps._close_db_connection()  # pylint: disable=protected-access


def _queue_warm_up(genebank_id):
    """Queue a warm-up unless one for the genebank is still waiting to start.

    A waiting one reads the latest snapshot when it starts; a running one may
    predate the write, so another is queued behind it.
    """
    with _warm_up_lock:
        fut = _warm_up_queued.get(genebank_id)
        if fut is not None and not fut.running() and not fut.done():
            return
        _warm_up_queued[genebank_id] = _warm_up_executor.submit(_warm_up_quietly, genebank_id)


def poll_debounce_keys():
    """
    Check for debounce keys ready to fire. Called every 5s by APScheduler on the leader.

    For each debounce:{genebank_id} key where now - timestamp >= 30s:
    delete the key and queue an eager recomputation. Every due key is
    claimed before any warm-up is queued, and the job returns at once: the
    warm-ups run on their own thread.
    """
    if _redis_client is None:
        return

    try:
        keys = _redis_client.keys("debounce:*")
    except redis.RedisError:
        return

    now = int(time.time())
    due = []
    for key in keys:
        try:
            val = _redis_client.get(key)
            if val is None:
                continue
            timestamp = int(val)
            if now - timestamp >= DEBOUNCE_DELAY_SECONDS:
                genebank_id = int(key.split(":")[1])
                _redis_client.delete(key)
                due.append(genebank_id)
        except (redis.RedisError, ValueError) as e:
            logger.warning(f"Error processing debounce key {key}: {e}")

    for genebank_id in due:
        _queue_warm_up(genebank_id)


def poll_genetics_version():
    """Leader job (5 s): publish a rebuild hint when the global genetics version moved.

    Only an optimisation — correctness rests on the snapshot key, not on the leader.
    """
    global _last_seen_version  # pylint: disable=global-statement
    from utils.data_access import get_all_genebanks
    from utils.database import read_genetics_version

    try:
        version = read_genetics_version()
    except Exception:
        logger.warning("Could not read the genetics version", exc_info=True)
        return
    if _last_seen_version is not None and version != _last_seen_version:
        for gb in get_all_genebanks():
            trigger_invalidation(gb.id)
    _last_seen_version = version
