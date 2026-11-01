"""Error types. The API layer maps them to HTTP status codes."""


class TsdbError(Exception):
    """Base class."""


class ValidationError(TsdbError):
    """Bad input (-> 400). Raised BEFORE anything touches the WAL."""


class FilterSyntaxError(ValidationError):
    """Unparseable tag filter (-> 400), with the character position."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(f"{message} at position {position}")
        self.position = position


class QueryLimitError(ValidationError):
    """Query would return too many series/points (-> 400)."""


class CorruptFileError(TsdbError):
    """Bad magic, checksum or offsets in an on-disk file."""


class FatalStorageError(TsdbError):
    """fsync / write failed after the WAL may be partly written.
    Policy: stop the process; recovery replays the WAL (see wal/writer.py)."""
