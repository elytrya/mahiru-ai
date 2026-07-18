from __future__ import annotations
import datetime as dt
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Float, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    memories: Mapped[list["Memory"]] = relationship(back_populates="user", cascade="all, delete")
    messages: Mapped[list["Message"]] = relationship(back_populates="user", cascade="all, delete")

class Personality(Base):
    __tablename__ = "personality"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="Mahiru")
    age: Mapped[int] = mapped_column(Integer, default=19)
    style: Mapped[str] = mapped_column(Text, default="естественный, живой, разговорный")
    character: Mapped[str] = mapped_column(Text, default="заботливая, спокойная, немного дерзкая")
    favorite_topics: Mapped[str] = mapped_column(Text, default="аниме, манга, музыка, космос")
    interests: Mapped[str] = mapped_column(Text, default="романтические истории, sci-fi")
    emotionality: Mapped[int] = mapped_column(Integer, default=45)
    humor: Mapped[int] = mapped_column(Integer, default=55)
    speech: Mapped[str] = mapped_column(Text, default="коротко, одной строкой, эмодзи почти не ставит, вопросы редко")
    relationship_: Mapped[str] = mapped_column("relationship", Text, default="её парень")
    avatar_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="Просто девушка, с которой можно поболтать по-человечески.")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

class MoodState(Base):
    __tablename__ = "mood_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mood: Mapped[str] = mapped_column(String(32), default="curious")
    intensity: Mapped[float] = mapped_column(Float, default=0.5)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fact: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), index=True)
    importance: Mapped[int] = mapped_column(Integer, default=50)
    source: Mapped[str] = mapped_column(String(64), default="chat")
    embedding: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="memories")

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="messages")

class AnimeHistory(Base):
    __tablename__ = "anime_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    anilist_id: Mapped[int | None] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="watching")
    score: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

class MangaHistory(Base):
    __tablename__ = "manga_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mangadex_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(256))
    chapter: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class ProviderSetting(Base):
    __tablename__ = "provider_settings"
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    extra: Mapped[dict | None] = mapped_column(JSON)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    run_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    done: Mapped[int] = mapped_column(Integer, default=0)
