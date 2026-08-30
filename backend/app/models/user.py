from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import UserRole
from app.database import Base
from app.models.base import CreatedAtMixin, db_enum


class User(Base, CreatedAtMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(db_enum(UserRole), nullable=False)
