"""Single local maintenance writer. A Docker administrator remains outside this boundary."""

import fcntl
from contextlib import contextmanager


@contextmanager
def maintenance_lock(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        path.chmod(0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another local maintenance operation is running") from None
        yield
