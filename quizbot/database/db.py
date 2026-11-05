"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
"""

from __future__ import annotations

import logging
from typing import Optional

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

logger = logging.getLogger(__name__)


class Database:
    """Shared Motor client/database holder and index setup."""

    def __init__(self, uri: str, db_name: str) -> None:
        self.uri = uri
        self.db_name = db_name
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None

    async def connect(self) -> None:
        if self._client is not None:
            return

        self._client = AsyncIOMotorClient(
            self.uri,
            serverSelectionTimeoutMS=15000,
            tz_aware=True,
        )

        self._db = self._client[self.db_name]

        await self._client.admin.command("ping")
        await self._ensure_indexes()

        logger.info(
            "Database connected: MongoDB Atlas (db=%s)",
            self.db_name,
        )

    async def _repair_leaderboard_duplicates(self) -> None:
        """
        Back up and remove duplicate leaderboard rows.

        One record is retained for each qid + user_id.
        Duplicate records are backed up before deletion.
        """

        assert self._db is not None

        leaderboard = self._db.leaderboard
        backup = self._db.leaderboard_duplicate_backup

        cursor = leaderboard.find({}).sort([
            ("qid", 1),
            ("user_id", 1),
            ("completed_at", 1),
            ("_id", 1),
        ])

        previous_key = None
        duplicate_ids = []
        backup_docs = []

        async for row in cursor:
            key = (row.get("qid"), row.get("user_id"))

            if key == previous_key:
                backup_docs.append(row)
                duplicate_ids.append(row["_id"])
            else:
                previous_key = key

            if len(backup_docs) >= 200:
                await self._backup_and_delete(
                    backup,
                    leaderboard,
                    backup_docs,
                    duplicate_ids,
                )

                backup_docs = []
                duplicate_ids = []

        if backup_docs:
            await self._backup_and_delete(
                backup,
                leaderboard,
                backup_docs,
                duplicate_ids,
            )

    async def _backup_and_delete(
        self,
        backup,
        leaderboard,
        backup_docs,
        duplicate_ids,
    ) -> None:
        """Safely back up duplicate rows and then delete originals."""

        for document in backup_docs:
            await backup.update_one(
                {"_id": document["_id"]},
                {"$setOnInsert": document},
                upsert=True,
            )

        await leaderboard.delete_many({
            "_id": {"$in": duplicate_ids}
        })

        logger.warning(
            "Backed up and removed %d duplicate leaderboard rows",
            len(duplicate_ids),
        )

    async def _ensure_indexes(self) -> None:
        """Create database indexes after repairing leaderboard duplicates."""

        assert self._db is not None
        db = self._db

        # Repair old duplicate entries before creating the unique index.
        await self._repair_leaderboard_duplicates()

        await db.users.create_index("chat_id", unique=True)
        await db.users.create_index([
            ("is_premium", 1),
            ("premium_until", 1),
        ])

        await db.quizzes.create_index("qid", unique=True)
        await db.quizzes.create_index("creator_id")
        await db.quizzes.create_index("quiz_name")
        await db.quizzes.create_index("search_indexed")

        await db.auth_chats.create_index(
            "creator_id",
            unique=True,
        )

        await db.payments.create_index("user_id")
        await db.payments.create_index("transaction_id")

        await db.ai_keys.create_index([
            ("user_id", 1),
            ("provider", 1),
        ])

        await db.quiz_attempts.create_index(
            "attempt_id",
            unique=True,
        )

        await db.quiz_attempts.create_index("user_id")
        await db.quiz_attempts.create_index("qid")

        await db.leaderboard.create_index(
            [("qid", 1), ("user_id", 1)],
            unique=True,
        )

        await db.leaderboard.create_index([
            ("qid", 1),
            ("score", -1),
            ("time_taken", 1),
        ])

        await db.question_wrong_stats.create_index(
            [("qid", 1), ("q_index", 1)],
            unique=True,
        )

        await db.user_mistakes.create_index(
            [("user_id", 1), ("qid", 1), ("q_index", 1)],
            unique=True,
        )

        await db.user_mistakes.create_index("user_id")

        await db.creator_settings.create_index(
            "user_id",
            unique=True,
        )

        await db.chat_settings.create_index(
            "chat_id",
            unique=True,
        )

        await db.user_quiz_prefs.create_index(
            "chat_id",
            unique=True,
        )

        await db.batches.create_index(
            "batch_id",
            unique=True,
        )

        await db.batches.create_index("creator_id")

        await db.batch_access.create_index(
            [("batch_id", 1), ("chat_id", 1)],
            unique=True,
        )

        await db.batch_quizzes.create_index(
            [("batch_id", 1), ("qid", 1)],
            unique=True,
        )

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None

            logger.info("Database connection closed")

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError(
                "Database not connected. Call connect() first."
            )

        return self._db

    def collection(self, name: str) -> AsyncIOMotorCollection:
        return self.db[name]


_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Return the process-wide Database singleton."""

    if _db_instance is None:
        raise RuntimeError(
            "Database not initialized. Call init_db(...) at startup."
        )

    return _db_instance


async def init_db(
    uri: str,
    db_name: str = "quizbot",
) -> Database:
    """Initialize and connect the shared database."""

    global _db_instance

    if _db_instance is None:
        _db_instance = Database(uri, db_name)

    await _db_instance.connect()

    return _db_instance


async def close_db() -> None:
    """Close the database connection."""

    global _db_instance

    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None
