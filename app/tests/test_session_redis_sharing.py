"""
Synthetic dual-Flask-app proof of Redis-backed session sharing (D-01/D-02),
sliding-expiry TTL refresh (D-07), and session-id regeneration deleting the
old key (D-10 layer 1, per D-11 layer 1).

herdbook.py's `APP` is a module-level singleton, so two independent Flask
app instances cannot be built from it in one process. These tests instead
build two minimal, independently-configured Flask apps that mirror
production's session config and prove the underlying mechanic: any two
Flask processes sharing the same Redis endpoint/db and SECRET_KEY see the
same session data through only the opaque sid cookie.
"""

import os
import socket
import struct
import threading
import time
import unittest
from urllib.parse import urlparse

import redis
from flask import Flask, session
from flask_session import Session
from utils.redis_retry import reconnect_on_drop

SESSION_REDIS_URL = os.getenv("SESSION_REDIS_URL", "redis://redis:6379/2")
SECRET = "shared-test-secret"

try:
    _inspect_redis = redis.Redis.from_url(SESSION_REDIS_URL, socket_connect_timeout=2, decode_responses=True)
    _inspect_redis.ping()
    REDIS_AVAILABLE = True
except Exception as exc:
    if os.getenv("CI"):
        # A silent skip in CI would false-green the cross-instance session proof.
        raise RuntimeError(f"Redis required in CI but unreachable at {SESSION_REDIS_URL}: {exc}") from exc
    REDIS_AVAILABLE = False


def _make_app(name, lifetime_seconds=60, redis_client=None):
    """Build a synthetic Flask app configured like herdbook.py's session block."""
    app = Flask(name)
    app.secret_key = SECRET
    app.config.update(
        SESSION_TYPE="redis",
        # decode_responses left at default False
        SESSION_REDIS=redis_client or redis.Redis.from_url(SESSION_REDIS_URL),
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=lifetime_seconds,
        SESSION_REFRESH_EACH_REQUEST=True,
    )
    Session(app)

    @app.route("/login")
    def login():
        session["user_id"] = "abc-123"
        return "ok"

    @app.route("/whoami")
    def whoami():
        return session.get("user_id", "anonymous")

    @app.route("/regen")
    def regen():
        app.session_interface.regenerate(session)
        return "regenerated"

    @app.route("/logout")
    def logout():
        session.clear()
        return "logged out"

    return app


class _FaultProxy:
    """TCP proxy to Redis that can reset its connections or stop answering."""

    def __init__(self, redis_url):
        target = urlparse(redis_url)
        self._target = (target.hostname, target.port or 6379)
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        self._clients = []
        self._doomed = set()
        self._swallow = False
        self._closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._closed:
            try:
                downstream, _ = self._listener.accept()
            except OSError:
                return
            upstream = socket.create_connection(self._target)
            self._clients.append(downstream)
            threading.Thread(target=self._pump, args=(downstream, upstream, True), daemon=True).start()
            threading.Thread(target=self._pump, args=(upstream, downstream, False), daemon=True).start()

    def _pump(self, src, dst, from_client):
        try:
            while data := src.recv(65536):
                if from_client and src in self._doomed:
                    # Linger 0 turns close() into an RST: the client's command is
                    # answered with "Connection reset by peer".
                    src.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    src.close()
                    dst.close()
                    return
                if from_client and self._swallow:
                    continue  # a hung Redis: the command is read, never answered
                dst.sendall(data)
        except OSError:
            pass

    def reset_open_connections(self):
        """Every connection open now dies on its next command; new ones work."""
        self._doomed = set(self._clients)

    def stop_answering(self):
        """Every command from now on is swallowed, as by a hung Redis."""
        self._swallow = True

    def close(self):
        self._closed = True
        self._listener.close()


def _sid_from_cookie(set_cookie_header):
    """Extract the raw sid from a `session=<sid>` Set-Cookie header."""
    return set_cookie_header.split(";")[0].split("=", 1)[1]


@unittest.skipUnless(REDIS_AVAILABLE, "Redis not available")
class TestSessionRedisSharing(unittest.TestCase):
    """Prove sessions are portable across independently-constructed Flask apps."""

    def setUp(self):
        _inspect_redis.flushdb()

    def tearDown(self):
        _inspect_redis.flushdb()

    def test_session_shared_across_two_flask_instances(self):
        """A session written by app A is readable by app B (D-01/D-02)."""
        app_a = _make_app("instance_a")
        app_b = _make_app("instance_b")
        # use_cookies=False: each client's own cookie jar would otherwise
        # override the manually-passed Cookie header below with nothing,
        # since client_b never visited app_a to populate its jar.
        client_a = app_a.test_client(use_cookies=False)
        client_b = app_b.test_client(use_cookies=False)

        resp_a = client_a.get("/login")
        cookie = resp_a.headers["Set-Cookie"].split(";")[0]

        resp_b = client_b.get("/whoami", headers={"Cookie": cookie})
        self.assertEqual(resp_b.data, b"abc-123")

    def test_sliding_ttl_refreshed_on_each_request(self):
        """Redis key TTL is refreshed on a later request, not just decaying (D-07)."""
        app = _make_app("instance_ttl", lifetime_seconds=5)
        client = app.test_client()

        resp = client.get("/login")
        cookie = resp.headers["Set-Cookie"].split(";")[0]
        sid = _sid_from_cookie(cookie)
        key = f"session:{sid}"

        ttl_after_login = _inspect_redis.ttl(key)
        self.assertGreater(ttl_after_login, 0)

        time.sleep(2)
        client.get("/whoami", headers={"Cookie": cookie})
        ttl_after_second_request = _inspect_redis.ttl(key)

        # Sliding expiry: the TTL after a later request should be refreshed
        # back up close to the full lifetime, not merely decremented by the
        # elapsed sleep — proves the clock resets on each request.
        self.assertGreaterEqual(ttl_after_second_request, ttl_after_login - 1)

    def test_sid_regeneration_deletes_old_key(self):
        """regenerate() mints a new sid and deletes the old Redis key (D-10)."""
        app = _make_app("instance_regen")
        client = app.test_client()

        resp = client.get("/login")
        cookie = resp.headers["Set-Cookie"].split(";")[0]
        old_sid = _sid_from_cookie(cookie)
        old_key = f"session:{old_sid}"
        self.assertTrue(_inspect_redis.exists(old_key))

        resp2 = client.get("/regen", headers={"Cookie": cookie})
        new_cookie = resp2.headers.get("Set-Cookie")
        self.assertIsNotNone(new_cookie)
        new_sid = _sid_from_cookie(new_cookie)

        self.assertNotEqual(new_sid, old_sid)
        self.assertFalse(_inspect_redis.exists(old_key))

    def test_logout_clear_deletes_redis_record(self):
        """session.clear() at logout deletes the Redis record, no orphan shell."""
        app = _make_app("instance_logout")
        client = app.test_client()

        resp = client.get("/login")
        cookie = resp.headers["Set-Cookie"].split(";")[0]
        key = f"session:{_sid_from_cookie(cookie)}"
        self.assertTrue(_inspect_redis.exists(key))

        resp2 = client.get("/logout", headers={"Cookie": cookie})
        self.assertFalse(_inspect_redis.exists(key))
        # The client is told to drop the cookie (empty value = delete_cookie)
        self.assertTrue(resp2.headers.get("Set-Cookie", "").startswith("session=;"))

    def _whoami_after_connection_drop(self, **client_kwargs):
        """Log in through a proxy, silently kill the pooled connection, read the session.

        The proxy answers the next command on the old connection with a TCP RST
        and no FIN beforehand — what a NAT/conntrack expiry looks like to the
        client, and what F11 hit. A plain
        CLIENT KILL sends a FIN, which redis-py already notices on checkout.
        """
        proxy = _FaultProxy(SESSION_REDIS_URL)
        try:
            db = SESSION_REDIS_URL.rsplit("/", 1)[1]
            app_redis = redis.Redis.from_url(f"redis://127.0.0.1:{proxy.port}/{db}", **client_kwargs)
            client = _make_app("instance_drop", redis_client=app_redis).test_client()
            cookie = client.get("/login").headers["Set-Cookie"].split(";")[0]
            proxy.reset_open_connections()
            try:
                resp = client.get("/whoami", headers={"Cookie": cookie})
            except redis.ConnectionError:
                return None
            return resp.status_code, resp.get_data(as_text=True)
        finally:
            proxy.close()

    def test_dropped_connection_fails_without_retry(self):
        """Control: without the retry settings the dead connection surfaces."""
        self.assertNotEqual(self._whoami_after_connection_drop(), (200, "abc-123"))

    def test_dropped_connection_is_retried(self):
        """With reconnect_on_drop() the request reconnects and keeps the session."""
        self.assertEqual(self._whoami_after_connection_drop(**reconnect_on_drop()), (200, "abc-123"))

    def test_hung_redis_fails_within_socket_timeout_on_health_check(self):
        """A due health check against a hung Redis must not retry its timeouts.

        Retry's default supported_errors include TimeoutError, and the
        health-check path honours them regardless of retry_on_error — without the
        narrowing in reconnect_on_drop() the PINGs go on well past socket_timeout.
        """
        proxy = _FaultProxy(SESSION_REDIS_URL)
        try:
            db = SESSION_REDIS_URL.rsplit("/", 1)[1]
            client = redis.Redis.from_url(
                f"redis://127.0.0.1:{proxy.port}/{db}",
                socket_connect_timeout=1,
                socket_timeout=1,
                health_check_interval=1,
                **reconnect_on_drop(),
            )
            client.ping()
            proxy.stop_answering()
            time.sleep(1.2)  # the pooled connection's health check is now due
            started = time.monotonic()
            with self.assertRaises(redis.RedisError):
                client.get("anything")
            self.assertLess(time.monotonic() - started, 2.5)
        finally:
            proxy.close()

    def test_herdbook_session_client_retries_dropped_connections(self):
        """The production session client carries the retry settings."""
        from herdbook import APP

        kwargs = APP.config["SESSION_REDIS"].connection_pool.connection_kwargs
        self.assertIn(redis.ConnectionError, kwargs["retry_on_error"])
        self.assertIsNotNone(kwargs["retry"])
