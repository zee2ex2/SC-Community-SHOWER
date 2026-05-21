from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    def __getitem__(self, key):
        return getattr(self, key)


class User(Base):
    __tablename__ = "users"
    discord_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    discord_tag: Mapped[str] = mapped_column(String(128), nullable=True)
    username: Mapped[str] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=True)
    avatar: Mapped[str] = mapped_column(Text, nullable=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[int] = mapped_column(Integer, default=0)
    role_ids: Mapped[str] = mapped_column(Text, default="", nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    role: Mapped["Role"] = relationship(back_populates="users")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    inventory: Mapped[list["CommunityInventory"]] = relationship(back_populates="user")
    orders: Mapped[list["OrderRequest"]] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    client_tokens: Mapped[list["ClientToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def role_level(self):
        return self.role.level if self.role else 1


class Session(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    discord_id: Mapped[str] = mapped_column(ForeignKey("users.discord_id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="sessions")


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    hasquality: Mapped[bool] = mapped_column(Boolean, default=False)
    code: Mapped[str] = mapped_column(String(32), nullable=True)
    catid: Mapped[int] = mapped_column(ForeignKey("itemcategory.id"), default=1)

    category: Mapped["ItemCategory"] = relationship(back_populates="items")


class ItemCategory(Base):
    __tablename__ = "itemcategory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int] = mapped_column(Integer, default=0)

    items: Mapped[list["Item"]] = relationship(back_populates="category")


class System(Base):
    __tablename__ = "systems"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)

    stations: Mapped[list["Station"]] = relationship(back_populates="system")


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("systems.id"), nullable=True)

    system: Mapped["System"] = relationship(back_populates="stations")


class CommunityInventory(Base):
    __tablename__ = "community_inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(ForeignKey("users.discord_id"))
    item_name: Mapped[str] = mapped_column(String(255))
    quality: Mapped[int] = mapped_column(Integer, default=100)
    quantity_scu: Mapped[float] = mapped_column(Float, default=1.0)
    station: Mapped[str] = mapped_column(Text, default="", nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="inventory")


class OrderRequest(Base):
    __tablename__ = "order_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(ForeignKey("users.discord_id"))
    item_name: Mapped[str] = mapped_column(String(255))
    min_quality: Mapped[int] = mapped_column(Integer, default=1)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    assigned_discord_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    fulfilled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="orders")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(ForeignKey("users.discord_id"))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="", nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="system")
    read: Mapped[bool] = mapped_column("read", Boolean, default=False, quote=True)
    dm_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="notifications")


class SyncLog(Base):
    __tablename__ = "sync_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String(64), nullable=True)
    direction: Mapped[str] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Config(Base):
    __tablename__ = "config"
    key: Mapped[str] = mapped_column("key", String(255), primary_key=True, quote=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    key: Mapped[str] = mapped_column("key", String(64), primary_key=True, quote=True)
    discord_id: Mapped[str] = mapped_column(ForeignKey("users.discord_id"))
    label: Mapped[str] = mapped_column(String(255), default="", nullable=True)
    last_used: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="api_keys")


class ClientToken(Base):
    __tablename__ = "client_tokens"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    discord_id: Mapped[str] = mapped_column(ForeignKey("users.discord_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="client_tokens")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    discord_role_id: Mapped[str] = mapped_column(String(64), nullable=True)
    is_env: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="role")
