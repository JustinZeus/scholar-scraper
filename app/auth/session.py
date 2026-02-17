from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request


SESSION_USER_ID_KEY = "auth_user_id"
SESSION_USER_EMAIL_KEY = "auth_user_email"
SESSION_USER_IS_ADMIN_KEY = "auth_user_is_admin"


@dataclass(frozen=True)
class SessionUser:
    id: int
    email: str
    is_admin: bool


def get_session_user(request: Request) -> SessionUser | None:
    user_id = request.session.get(SESSION_USER_ID_KEY)
    email = request.session.get(SESSION_USER_EMAIL_KEY)
    is_admin = request.session.get(SESSION_USER_IS_ADMIN_KEY)
    if user_id is None or email is None or is_admin is None:
        return None
    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    if not isinstance(email, str):
        return None
    return SessionUser(id=parsed_user_id, email=email, is_admin=bool(is_admin))


def set_session_user(
    request: Request,
    *,
    user_id: int,
    email: str,
    is_admin: bool,
) -> None:
    request.session[SESSION_USER_ID_KEY] = int(user_id)
    request.session[SESSION_USER_EMAIL_KEY] = email
    request.session[SESSION_USER_IS_ADMIN_KEY] = bool(is_admin)


def clear_session_user(request: Request) -> None:
    request.session.pop(SESSION_USER_ID_KEY, None)
    request.session.pop(SESSION_USER_EMAIL_KEY, None)
    request.session.pop(SESSION_USER_IS_ADMIN_KEY, None)
