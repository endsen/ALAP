"""Authorization rows can be locked without giving workers UPDATE privileges."""


def lock_read(db, kind, *keys):
    values = tuple(keys) + ("",) * (3 - len(keys))
    db.execute("SELECT lock_read_record(%s,%s,%s,%s)", (kind, *values))
