"""A single SQLite worker with checked files and transactional migrations."""
from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from .errors import DatabaseProgrammingError, DatabaseUnavailable, SchemaVersionError
from .models import utc_now

MIGRATIONS = ("001_initial.sql", "002_adaptive.sql")


class SQLiteDatabase:
    """Own a database connection and execute its work on one dedicated thread."""

    def __init__(self, path: str | Path, *, timeout: float = 0.25) -> None:
        if str(path) == ':memory:' or not str(path).strip():
            raise ValueError("A persistent database path is required")
        if timeout < 0 or timeout > 30:
            raise ValueError("Database timeout must be between zero and 30 seconds")
        self.path = Path(path).expanduser().resolve()
        self.timeout = timeout
        self.process_id = uuid4().hex
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="matheutic-storage")
        self._connection: sqlite3.Connection | None = None
        self._file_identity: tuple[int, int] | None = None
        self._closed = False

    async def _call(self, function, *args):
        if self._closed:
            raise DatabaseUnavailable("The learner database is closed")
        try:
            return await asyncio.get_running_loop().run_in_executor(self._executor, function, *args)
        except sqlite3.ProgrammingError as error:
            raise DatabaseProgrammingError("A learner database operation was invalid") from error
        except (sqlite3.Error, OSError) as error:
            raise DatabaseUnavailable("The learner database could not be accessed") from error

    async def open(self) -> None:
        """Initialize or validate the database before learner turns are accepted."""
        await self._call(self._open)

    def _open(self) -> None:
        if self._connection is not None:
            self._db()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            
            if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise SchemaVersionError("SQLite foreign-key enforcement is unavailable")
            
            if [row[0] for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
                raise DatabaseUnavailable("The learner database failed its integrity check")
            
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise SchemaVersionError("The learner database requires a newer application")
            
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if tables and "schema_migrations" not in tables:
                raise SchemaVersionError("The selected file is not a Matheutic learner database")
            
            applied = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")] if tables else []
            if applied != list(range(1, version + 1)):
                raise SchemaVersionError("Database migration records are inconsistent")
            
            for next_version in range(version + 1, len(MIGRATIONS) + 1):
                script = files("storage").joinpath("migrations", MIGRATIONS[next_version - 1]).read_text()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    statement = ""
                    for line in script.splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            connection.execute(statement)
                            statement = ""
                    if statement.strip():
                        raise SchemaVersionError("Incomplete database migration")
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", 
                        (next_version, utc_now()),
                        )
                    connection.execute(f"PRAGMA user_version = {next_version}")
                    connection.execute("COMMIT")
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise DatabaseUnavailable("The learner database contains broken relationships")
            info = self.path.stat()
            self._file_identity = (info.st_dev, info.st_ino)
            self._connection = connection
            self._db()
        except BaseException:
            self._connection = None
            connection.close()
            raise

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise DatabaseUnavailable("The learner database has not been opened")
        info = self.path.stat()
        if (info.st_dev, info.st_ino) != self._file_identity or not info.st_mode & 0o222:
            raise DatabaseUnavailable("The running learner database was replaced or is not writable")
        return self._connection

    async def close(self) -> None:
        """Close the connection on its owning thread and release the worker."""
        if self._closed:
            return
        try:
            await self._call(self._close)
        finally:
            self._closed = True
            self._executor.shutdown(wait=True)

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
