from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UserState:
    name: str | None = None
    data: dict = field(default_factory=dict)


_states: dict[int, UserState] = {}


def get_state(user_id: int) -> UserState:
    return _states.setdefault(user_id, UserState())


def state_name(user_id: int) -> str | None:
    return get_state(user_id).name


def state_data(user_id: int) -> dict:
    return dict(get_state(user_id).data)


def set_state(user_id: int, name: str, **data) -> None:
    state = get_state(user_id)
    state.name = name
    state.data.update(data)


def update_state(user_id: int, **data) -> None:
    get_state(user_id).data.update(data)


def clear_state(user_id: int) -> None:
    _states.pop(user_id, None)
