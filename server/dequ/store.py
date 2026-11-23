"""Put, answer and withdraw cards, and record decisions. Expired cards are deleted before each operation."""

import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from .config import Retention
from .schema import Agent, Answer, CardRequest, DecisionRecord


class NotFound(Exception):
    pass


class AlreadyAnswered(Exception):
    pass


class InvalidOption(Exception):
    pass


@dataclass(frozen=True)
class AskResult:
    id: str
    created: bool
    status: Literal["pending", "answered"]
    answer: Answer | None


@dataclass(frozen=True)
class Card:
    id: str
    request: CardRequest
    created_at: datetime


@dataclass(frozen=True)
class FirestoreBell:
    """A Firestore document a hosted store can write when a pending card changes."""

    project: str
    database: str
    bell: str
    expires_at: datetime


@dataclass(frozen=True)
class CardResult:
    status: Literal["pending", "answered", "gone"]
    answer: Answer | None
    notification: FirestoreBell | None = None


@dataclass(frozen=True)
class HistoryEntry:
    id: str
    by: Literal["human", "ai"]
    agent: Agent
    question: str
    chose: str | None
    comment: str
    why: str | None
    at: datetime


class CardStore(Protocol):
    """What the app calls on whichever store a request's token resolved to."""

    def ask(self, req: CardRequest) -> AskResult: ...

    def pending(self) -> list[Card]: ...

    def answer(self, card_id: str, answer: Answer) -> None: ...

    def results(self, ids: list[str]) -> dict[str, CardResult]: ...

    def withdraw(self, card_id: str) -> None: ...

    def record(self, rec: DecisionRecord) -> str: ...

    def history(self) -> list[HistoryEntry]: ...


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _chose_label(request: CardRequest, answer: Answer) -> str | None:
    if answer.option is None:
        return None
    for option in request.options:
        if option.id == answer.option:
            return option.label
    return None


def _card_expired(row: sqlite3.Row, now: datetime, retention: Retention) -> bool:
    if row["answered_at"] is not None:
        return _parse(row["answered_at"]) + retention.answered <= now
    return _parse(row["created_at"]) + retention.pending <= now


class Store:
    def __init__(self, path: Path, retention: Retention, clock: Callable[[], datetime]) -> None:
        self.path = path
        self.retention = retention
        self.clock = clock
        self._ensure_schema()

    def ask(self, req: CardRequest) -> AskResult:
        with self._tx() as (conn, now):
            if req.key is not None:
                existing = _card_by_key(conn, req.key)
                if existing is not None:
                    return _ask_result(existing, created=False)
            card_id = secrets.token_hex(16)
            try:
                conn.execute(
                    """
                    INSERT INTO cards (id, key, request_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (card_id, req.key, req.model_dump_json(), _iso(now)),
                )
            except sqlite3.IntegrityError:
                # When the partial unique index is hit, return the card that got in first.
                existing = _card_by_key(conn, req.key) if req.key is not None else None
                if existing is None:
                    raise
                return _ask_result(existing, created=False)
            return AskResult(id=card_id, created=True, status="pending", answer=None)

    def pending(self) -> list[Card]:
        with self._tx() as (conn, _now):
            rows = conn.execute(
                """
                SELECT id, request_json, created_at
                FROM cards
                WHERE answered_at IS NULL
                ORDER BY rowid
                """
            ).fetchall()
            return [
                Card(
                    id=row["id"],
                    request=CardRequest.model_validate_json(row["request_json"]),
                    created_at=_parse(row["created_at"]),
                )
                for row in rows
            ]

    def answer(self, card_id: str, answer: Answer) -> None:
        with self._tx() as (conn, now):
            row = _card_by_id(conn, card_id)
            if row is None:
                raise NotFound(card_id)
            if row["answered_at"] is not None:
                raise AlreadyAnswered(card_id)
            request = CardRequest.model_validate_json(row["request_json"])
            if answer.option is not None and all(option.id != answer.option for option in request.options):
                raise InvalidOption(answer.option)
            conn.execute(
                "UPDATE cards SET answered_at = ?, answer_json = ? WHERE id = ?",
                (_iso(now), answer.model_dump_json(), card_id),
            )

    def results(self, ids: list[str]) -> dict[str, CardResult]:
        with self._tx() as (conn, _now):
            found = {}
            if ids:
                placeholders = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT id, answered_at, answer_json FROM cards WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()
                found = {row["id"]: row for row in rows}
            out: dict[str, CardResult] = {}
            for card_id in ids:
                row = found.get(card_id)
                if row is None:
                    out[card_id] = CardResult(status="gone", answer=None)
                elif row["answered_at"] is None:
                    out[card_id] = CardResult(status="pending", answer=None)
                else:
                    out[card_id] = CardResult(
                        status="answered",
                        answer=Answer.model_validate_json(row["answer_json"]),
                    )
            return out

    def withdraw(self, card_id: str) -> None:
        answered = False
        with self._tx() as (conn, _now):
            row = _card_by_id(conn, card_id)
            if row is None:
                raise NotFound(card_id)
            if row["answered_at"] is not None:
                answered = True
            else:
                conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
                return
        if answered:
            raise AlreadyAnswered(card_id)

    def record(self, rec: DecisionRecord) -> str:
        with self._tx() as (conn, now):
            record_id = secrets.token_hex(16)
            conn.execute(
                "INSERT INTO decisions (id, record_json, recorded_at) VALUES (?, ?, ?)",
                (record_id, rec.model_dump_json(), _iso(now)),
            )
            return record_id

    def history(self) -> list[HistoryEntry]:
        with self._tx() as (conn, _now):
            entries: list[HistoryEntry] = []
            for row in conn.execute(
                """
                SELECT id, request_json, answered_at, answer_json
                FROM cards
                WHERE answered_at IS NOT NULL
                """
            ):
                request = CardRequest.model_validate_json(row["request_json"])
                answer = Answer.model_validate_json(row["answer_json"])
                entries.append(
                    HistoryEntry(
                        id=row["id"],
                        by="human",
                        agent=request.agent,
                        question=request.question,
                        chose=_chose_label(request, answer),
                        comment=answer.comment,
                        why=None,
                        at=_parse(row["answered_at"]),
                    )
                )
            for row in conn.execute("SELECT id, record_json, recorded_at FROM decisions"):
                rec = DecisionRecord.model_validate_json(row["record_json"])
                entries.append(
                    HistoryEntry(
                        id=row["id"],
                        by="ai",
                        agent=rec.agent,
                        question=rec.question,
                        chose=rec.chose,
                        comment="",
                        why=rec.why,
                        at=_parse(row["recorded_at"]),
                    )
                )
            entries.sort(key=lambda entry: entry.at, reverse=True)
            return entries

    def _connect(self) -> sqlite3.Connection:
        # Turn off implicit transactions. Writes are serialized with BEGIN IMMEDIATE.
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cards (
                    id TEXT PRIMARY KEY,
                    key TEXT,
                    request_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    answered_at TEXT,
                    answer_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS cards_key_unique
                ON cards (key)
                WHERE key IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[tuple[sqlite3.Connection, datetime]]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = self.clock()
            self._purge(conn, now)
            yield conn, now
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _purge(self, conn: sqlite3.Connection, now: datetime) -> None:
        expired_cards = [
            row["id"]
            for row in conn.execute("SELECT id, created_at, answered_at FROM cards")
            if _card_expired(row, now, self.retention)
        ]
        conn.executemany("DELETE FROM cards WHERE id = ?", [(card_id,) for card_id in expired_cards])
        expired_decisions = [
            row["id"]
            for row in conn.execute("SELECT id, recorded_at FROM decisions")
            if _parse(row["recorded_at"]) + self.retention.answered <= now
        ]
        conn.executemany(
            "DELETE FROM decisions WHERE id = ?",
            [(decision_id,) for decision_id in expired_decisions],
        )


def _card_by_id(conn: sqlite3.Connection, card_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, request_json, created_at, answered_at, answer_json
        FROM cards
        WHERE id = ?
        """,
        (card_id,),
    ).fetchone()


def _card_by_key(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, request_json, created_at, answered_at, answer_json
        FROM cards
        WHERE key = ?
        """,
        (key,),
    ).fetchone()


def _ask_result(row: sqlite3.Row, *, created: bool) -> AskResult:
    if row["answered_at"] is None:
        return AskResult(id=row["id"], created=created, status="pending", answer=None)
    return AskResult(
        id=row["id"],
        created=created,
        status="answered",
        answer=Answer.model_validate_json(row["answer_json"]),
    )
