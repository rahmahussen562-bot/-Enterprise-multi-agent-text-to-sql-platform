"""Cooperative request cancellation with synchronized native driver callbacks."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading


class QueryCancelledError(RuntimeError):
    pass


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._callbacks = {}
        self.failures = []

    @property
    def cancelled(self):
        return self._event.is_set()

    def check(self):
        if self.cancelled:
            raise QueryCancelledError("Query cancellation requested.")

    def register(self, callback):
        key = object()
        with self._lock:
            self.check()
            self._callbacks[key] = callback
        return key

    def unregister(self, key):
        with self._lock:
            self._callbacks.pop(key, None)

    def cancel(self):
        # Driver cancellation runs on a dedicated control thread, never ASGI's
        # event loop. The lock prevents a callback racing resource closure.
        self._event.set()
        with self._lock:
            callbacks, self._callbacks = self._callbacks, {}
            for callback in callbacks.values():
                try:
                    callback()
                except Exception as error:
                    self.failures.append(type(error).__name__)


current_cancellation = ContextVar("sentinel_cancellation", default=None)


@contextmanager
def cancellation_context(token):
    marker = current_cancellation.set(token)
    try:
        token.check()
        yield
    finally:
        current_cancellation.reset(marker)


def check_cancelled():
    token = current_cancellation.get()
    if token is not None:
        token.check()


class _CursorLease:
    def __init__(self, cursor, token, keys):
        self._cursor = cursor
        self._token = token
        self._keys = keys
        self._key = token.register(cursor.cancel)
        keys.append(self._key)

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def execute(self, *args, **kwargs):
        self._token.check()
        try:
            self._cursor.execute(*args, **kwargs)
        except Exception:
            self._token.check()
            raise
        self._token.check()
        return self

    def close(self):
        self._token.unregister(self._key)
        self._cursor.close()


class _ConnectionLease:
    def __init__(self, connection, token, keys):
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_token", token)
        object.__setattr__(self, "_keys", keys)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __setattr__(self, name, value):
        setattr(self._connection, name, value)

    def cursor(self):
        self._token.check()
        cursor = self._connection.cursor()
        try:
            return _CursorLease(cursor, self._token, self._keys)
        except BaseException:
            cursor.close()
            raise


@contextmanager
def cancellable_connection(connection, native_odbc):
    token = current_cancellation.get()
    if token is None:
        yield connection
        return
    token.check()
    keys = []
    try:
        if native_odbc:
            yield _ConnectionLease(connection, token, keys)
        else:
            keys.append(token.register(connection.interrupt))
            yield connection
    finally:
        for key in keys:
            token.unregister(key)
