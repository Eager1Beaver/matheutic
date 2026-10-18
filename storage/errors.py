"""Controlled failures."""


class StorageError(Exception):
    """Learner data could not be safely loaded or saved."""


class DatabaseUnavailable(StorageError):
    """The database cannot currently be accessed."""


class SchemaVersionError(StorageError):
    """The database schema is incompatible with this application."""


class StateRecoveryError(StorageError):
    """Saved conversation state failed validation."""


class SessionConflict(StorageError):
    """A turn refers to a session revision that is no longer current."""
