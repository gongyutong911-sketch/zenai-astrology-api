"""SQLite 用户档案与测算历史。"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, object_session, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "zenai.db"
GUIDANCE_FIELDS = (
    "core_energy",
    "career_guidance",
    "relationship_advice",
    "wealth_flow",
    "action_tips",
    "lucky_elements",
)
# 免费版开放前三个觉察维度；后三个行动方案与状态复盘属于 Pro / VIP。
FREE_FIELDS = ("core_energy", "career_guidance", "relationship_advice")
DAILY_SIGN_FIELDS = FREE_FIELDS
TIER_FREE = "free"
TIER_ONE_TIME = "one_time_pro"
TIER_MONTHLY = "monthly_subscriber"
TIER_YEARLY = "yearly_subscriber"
MEMBERSHIP_TIERS = (TIER_FREE, TIER_ONE_TIME, TIER_MONTHLY, TIER_YEARLY)
PREMIUM_TIERS = frozenset((TIER_ONE_TIME, TIER_MONTHLY, TIER_YEARLY))
HISTORY_TIERS = frozenset((TIER_MONTHLY, TIER_YEARLY))
SUBSCRIBER_TIERS = HISTORY_TIERS
PLAN_TYPES = {
    "one_time": TIER_ONE_TIME,
    "monthly": TIER_MONTHLY,
    "yearly": TIER_YEARLY,
}
SUBSCRIPTION_LENGTH = {
    TIER_MONTHLY: timedelta(days=30),
    TIER_YEARLY: timedelta(days=365),
}
TIER_LABELS = {
    TIER_FREE: "免费版",
    TIER_ONE_TIME: "单次深度破局报告",
    TIER_MONTHLY: "月度能量守护",
    TIER_YEARLY: "年度能量守护",
}


class UnknownUser(LookupError):
    """请求里的用户 ID 或 Token 对不上已有档案。"""


class ConflictingIdentity(ValueError):
    """同时给出的用户 ID 与 Token 指向不同档案。"""


class InvalidMembership(ValueError):
    """会员等级或订阅方案不受支持。"""


class DeepReportLocked(PermissionError):
    """没有有效订阅特权，也没有剩余的深度测算次数。"""

    def __init__(self, credits: int):
        super().__init__("深度测算尚未开通")
        self.credits = credits


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    birth_date: Mapped[str] = mapped_column(String(32), nullable=False)
    birth_time: Mapped[str] = mapped_column(String(16), nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    membership_tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TIER_FREE, server_default=TIER_FREE
    )
    is_subscriber: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    one_time_credits: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    readings: Mapped[list["ReadingHistory"]] = relationship(
        back_populates="user",
        order_by="ReadingHistory.created_at.desc()",
    )


class ReadingHistory(Base):
    __tablename__ = "reading_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    birth_date: Mapped[str] = mapped_column(String(32), nullable=False)
    birth_time: Mapped[str] = mapped_column(String(16), nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    core_energy: Mapped[str] = mapped_column(Text, nullable=False)
    career_guidance: Mapped[str] = mapped_column(Text, nullable=False)
    relationship_advice: Mapped[str] = mapped_column(Text, nullable=False)
    wealth_flow: Mapped[str] = mapped_column(Text, nullable=False)
    action_tips: Mapped[str] = mapped_column(Text, nullable=False)
    lucky_elements: Mapped[str] = mapped_column(Text, nullable=False)
    user: Mapped[User] = relationship(back_populates="readings")


class DeepReportLedger(Base):
    """深度测算的购买与消耗记录。日常能量指引不写这张表。"""

    __tablename__ = "deep_report_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    credits_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


engine = None
SessionLocal = None
_configured_url = None


def database_url() -> str:
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_DB_PATH}"


def _engine_options(url: str) -> dict:
    if not url.startswith("sqlite"):
        return {}
    options = {"connect_args": {"check_same_thread": False}}
    if url in {"sqlite://", "sqlite:///:memory:"}:
        options["poolclass"] = StaticPool
    return options


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def configure_database(url: Optional[str] = None) -> None:
    """按 DATABASE_URL 建库。同一地址重复调用时沿用已有连接。"""
    global engine, SessionLocal, _configured_url
    resolved = url or database_url()
    if engine is not None and _configured_url == resolved:
        return
    engine = create_engine(resolved, **_engine_options(resolved))
    if resolved.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    ensure_membership_columns(engine)
    _configured_url = resolved


def ensure_membership_columns(target_engine=None) -> None:
    """给已存在的 SQLite 用户表补上会员字段，不影响新库。"""
    target = target_engine or engine
    if target.dialect.name != "sqlite":
        return
    with target.begin() as conn:
        names = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        if "membership_tier" not in names:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN membership_tier VARCHAR(32) NOT NULL DEFAULT 'free'"
            )
        if "is_subscriber" not in names:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN is_subscriber BOOLEAN NOT NULL DEFAULT 0"
            )
        if "expires_at" not in names:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN expires_at DATETIME")
        if "one_time_credits" not in names:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN one_time_credits INTEGER NOT NULL DEFAULT 0"
            )
        conn.exec_driver_sql(
            "UPDATE users SET membership_tier = 'one_time_pro' WHERE membership_tier = 'pro_report'"
        )
        conn.exec_driver_sql(
            "UPDATE users SET membership_tier = 'monthly_subscriber', is_subscriber = 1 "
            "WHERE membership_tier = 'vip_subscriber'"
        )


def reset_database() -> None:
    """清空并重建表，供测试隔离使用。"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def subscription_expired(expires_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    """用 UTC 当前时间判断订阅是否已过 expires_at。没有到期时间时不视为过期。"""
    if expires_at is None:
        return False
    current = _naive_utc(now or datetime.utcnow())
    return current > _naive_utc(expires_at)


def _clean_token(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    token = value.strip()
    return token or None


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "token": user.token,
        "birth_date": user.birth_date,
        "birth_time": user.birth_time,
        "gender": user.gender,
        "created_at": user.created_at,
        "membership_tier": user.membership_tier,
        "is_subscriber": bool(user.is_subscriber),
        "expires_at": user.expires_at,
        "one_time_credits": int(user.one_time_credits or 0),
    }


def _reading_payload(reading: ReadingHistory) -> dict:
    payload = {
        "id": reading.id,
        "user_id": reading.user_id,
        "birth_date": reading.birth_date,
        "birth_time": reading.birth_time,
        "gender": reading.gender,
        "question": reading.question,
        "created_at": reading.created_at,
    }
    for field in GUIDANCE_FIELDS:
        payload[field] = getattr(reading, field)
    return payload


def _find_user(session, user_id: Optional[int], user_token: Optional[str]) -> Optional[User]:
    by_id = session.get(User, user_id) if user_id is not None else None
    by_token = None
    if user_token:
        by_token = session.scalar(select(User).where(User.token == user_token))
    if user_id is not None and by_id is None:
        raise UnknownUser("未找到对应用户")
    if user_token and by_token is None:
        raise UnknownUser("未找到对应用户")
    if by_id is not None and by_token is not None and by_id.id != by_token.id:
        raise ConflictingIdentity("用户标识不一致")
    return by_id or by_token


def remember_reading(
    *,
    birth_date: str,
    birth_time: str,
    gender: str,
    question: str,
    guidance: dict,
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
) -> dict:
    """写入一次测算。没有身份时新建用户并签发 Token。"""
    token = _clean_token(user_token)
    with SessionLocal() as session:
        user = _find_user(session, user_id, token)
        if user is None:
            user = User(
                token=secrets.token_urlsafe(24),
                birth_date=birth_date,
                birth_time=birth_time,
                gender=gender,
                created_at=_utcnow(),
            )
            session.add(user)
            session.flush()
        else:
            user.birth_date = birth_date
            user.birth_time = birth_time
            user.gender = gender

        reading = ReadingHistory(
            user_id=user.id,
            birth_date=birth_date,
            birth_time=birth_time,
            gender=gender,
            question=question,
            created_at=_utcnow(),
            **{field: guidance[field] for field in GUIDANCE_FIELDS},
        )
        session.add(reading)
        session.commit()
        return {"user": _user_payload(user), "reading": _reading_payload(reading)}


def list_readings(*, user_id: Optional[int] = None, user_token: Optional[str] = None) -> dict:
    """按用户 ID 或 Token 取回档案，新的测算排在前面。"""
    token = _clean_token(user_token)
    if user_id is None and not token:
        raise ValueError("请提供 user_id 或 user_token")
    with SessionLocal() as session:
        user = _find_user(session, user_id, token)
        if user is None:
            raise UnknownUser("未找到对应用户")
        check_and_update_subscription(user)
        readings = session.scalars(
            select(ReadingHistory)
            .where(ReadingHistory.user_id == user.id)
            .order_by(ReadingHistory.created_at.desc(), ReadingHistory.id.desc())
        ).all()
        return {
            "user": _user_payload(user),
            "readings": [_reading_payload(item) for item in readings],
        }


def access_for_tier(tier: str) -> dict:
    """把会员等级展开成接口可返回的权益说明。"""
    if tier not in MEMBERSHIP_TIERS:
        raise InvalidMembership("不支持的会员等级")
    premium = tier in PREMIUM_TIERS
    unlocked = GUIDANCE_FIELDS if premium else FREE_FIELDS
    locked = tuple(field for field in GUIDANCE_FIELDS if field not in unlocked)
    if tier == TIER_YEARLY:
        message = "年度能量守护已生效，全年可以无限制查看深度洞察，并回看每一次状态复盘。"
        access = "full_coaching"
    elif tier == TIER_MONTHLY:
        message = "月度能量守护已生效，高阶维度、深度报告和状态复盘都可以随时查看。"
        access = "full_coaching"
    elif tier == TIER_ONE_TIME:
        message = "单次深度破局报告已开通，财富行动、破局锦囊和每日幸运指引已打开。状态复盘属于月度或年度守护。"
        access = "full_coaching"
    else:
        message = (
            "当前为免费版，已打开能量状态诊断：核心能量、事业觉察、关系觉察。"
            "财富行动、破局锦囊和每日幸运指引可单次开通，状态复盘属于月度或年度守护。"
        )
        access = "foundation"
    return {
        "tier": tier,
        "is_subscriber": tier in SUBSCRIBER_TIERS,
        "label": TIER_LABELS[tier],
        "access": access,
        "unlocked_fields": list(unlocked),
        "locked_fields": list(locked),
        "history_unlocked": tier in HISTORY_TIERS,
        "message": message,
    }


def membership_view(tier: str, expires_at: Optional[datetime] = None) -> dict:
    """权益说明加上到期时间。免费档若留有过去的到期时间，提示订阅已过期。"""
    payload = access_for_tier(tier)
    payload["expires_at"] = expires_at
    if tier == TIER_FREE and subscription_expired(expires_at):
        payload["message"] = (
            "订阅已过期，已回到免费版。"
            "核心能量、事业觉察和关系觉察仍然开放，深度报告与状态复盘需要重新开通。"
        )
    return payload


def _member_payload(user: User) -> dict:
    payload = membership_view(user.membership_tier, user.expires_at)
    payload.update(
        {
            "user_id": user.id,
            "user_token": user.token,
            "is_subscriber": bool(user.is_subscriber),
            "known": True,
        }
    )
    return payload


def resolve_member(*, user_id: Optional[int] = None, user_token: Optional[str] = None) -> dict:
    """按用户 ID 或 Token 读取权益；没有身份时视为免费访客。"""
    token = _clean_token(user_token)
    if user_id is None and not token:
        payload = access_for_tier(TIER_FREE)
        payload.update({"user_id": None, "user_token": None, "known": False})
        return payload
    with SessionLocal() as session:
        user = _find_user(session, user_id, token)
        if user is None:
            raise UnknownUser("未找到对应用户")
        check_and_update_subscription(user)
        return _member_payload(user)


def combine_identity(
    resolved: dict,
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
) -> dict:
    """合并请求头里已经识别的身份，以及正文或查询参数中的 Token。"""
    token = _clean_token(user_token)
    if resolved.get("user_id") is not None and user_id is not None and resolved["user_id"] != user_id:
        raise ConflictingIdentity("用户标识不一致")
    if resolved.get("user_token") and token and resolved["user_token"] != token:
        raise ConflictingIdentity("用户标识不一致")
    merged_id = resolved.get("user_id") if resolved.get("user_id") is not None else user_id
    merged_token = resolved.get("user_token") or token
    if merged_id == resolved.get("user_id") and merged_token == resolved.get("user_token"):
        return resolved
    return resolve_member(user_id=merged_id, user_token=merged_token)


def set_membership(
    *,
    tier: str,
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
) -> dict:
    """写入会员等级。月订阅和年订阅会把 is_subscriber 标为真。"""
    if tier not in MEMBERSHIP_TIERS:
        raise InvalidMembership("不支持的会员等级")
    with SessionLocal() as session:
        user = _find_user(session, user_id, _clean_token(user_token))
        if user is None:
            raise UnknownUser("未找到对应用户")
        user.membership_tier = tier
        user.is_subscriber = tier in SUBSCRIBER_TIERS
        length = SUBSCRIPTION_LENGTH.get(tier)
        user.expires_at = _utcnow() + length if length is not None else None
        session.commit()
        return _member_payload(user)


def check_and_update_subscription(user: User) -> User:
    """月订阅或年订阅超过 expires_at 时降回免费档，并保留到期时间以便追溯。"""
    if user.membership_tier not in SUBSCRIBER_TIERS or not subscription_expired(user.expires_at):
        return user
    user.membership_tier = TIER_FREE
    user.is_subscriber = False
    session = object_session(user)
    if session is not None:
        session.commit()
    return user


def _write_deep_ledger(session, user: User, event_type: str, credits_delta: int) -> None:
    session.add(
        DeepReportLedger(
            user_id=user.id,
            event_type=event_type,
            credits_delta=credits_delta,
            balance_after=int(user.one_time_credits or 0),
            created_at=_utcnow(),
        )
    )


def grant_deep_credits(
    *,
    quantity: int = 1,
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
) -> dict:
    """模拟购买深度测算次数。不改变日常能量指引的会员档位。"""
    if quantity < 1 or quantity > 99:
        raise InvalidMembership("购买次数需要在 1 到 99 之间")
    with SessionLocal() as session:
        user = _find_user(session, user_id, _clean_token(user_token))
        if user is None:
            raise UnknownUser("未找到对应用户")
        user.one_time_credits = int(user.one_time_credits or 0) + quantity
        _write_deep_ledger(session, user, "grant", quantity)
        session.commit()
        payload = _member_payload(user)
        payload["one_time_credits"] = int(user.one_time_credits or 0)
        return payload


def authorize_deep_report(
    *,
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
) -> dict:
    """有效月卡或年卡直接放行；否则消耗 1 次单次额度。"""
    with SessionLocal() as session:
        user = _find_user(session, user_id, _clean_token(user_token))
        if user is None:
            raise UnknownUser("未找到对应用户")
        check_and_update_subscription(user)
        if user.membership_tier in SUBSCRIBER_TIERS and bool(user.is_subscriber):
            _write_deep_ledger(session, user, "subscription_pass", 0)
            session.commit()
            payload = _member_payload(user)
            payload["access_via"] = "subscription"
            payload["one_time_credits"] = int(user.one_time_credits or 0)
            return payload
        credits = int(user.one_time_credits or 0)
        if credits <= 0:
            raise DeepReportLocked(credits)
        user.one_time_credits = credits - 1
        _write_deep_ledger(session, user, "consume", -1)
        session.commit()
        payload = _member_payload(user)
        payload["access_via"] = "credit"
        payload["one_time_credits"] = int(user.one_time_credits or 0)
        return payload


def apply_plan(
    plan_type: str,
    *,
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
) -> dict:
    """把模拟开通的方案写成对应会员档位。"""
    tier = PLAN_TYPES.get((plan_type or "").strip())
    if tier is None:
        raise InvalidMembership("不支持的订阅方案")
    return set_membership(tier=tier, user_id=user_id, user_token=user_token)


def guidance_for_storage(guidance: dict, tier: str) -> dict:
    """未解锁的维度以空字符串入库，避免免费请求留下深度内容。"""
    unlocked = set(access_for_tier(tier)["unlocked_fields"])
    return {
        field: (guidance.get(field) or "").strip() if field in unlocked else ""
        for field in GUIDANCE_FIELDS
    }


def present_reading(reading: dict, tier: str) -> dict:
    """按当前权益去掉未解锁或当时没有生成的维度。"""
    unlocked = set(access_for_tier(tier)["unlocked_fields"])
    presented = {
        "id": reading["id"],
        "user_id": reading["user_id"],
        "created_at": reading["created_at"],
        "birth_date": reading["birth_date"],
        "birth_time": reading["birth_time"],
        "gender": reading["gender"],
        "question": reading["question"],
    }
    for field in GUIDANCE_FIELDS:
        value = (reading.get(field) or "").strip()
        if field in unlocked and value:
            presented[field] = value
    return presented


configure_database()
