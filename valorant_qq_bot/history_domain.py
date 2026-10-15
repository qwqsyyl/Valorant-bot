"""Small, credential-free contract for completed CN match history."""
from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True)
class HistoryMatch:
    match_id: str
    played_at: int | None
    mode: str
    map_name: str
    agent: str
    result: str
    own_score: int | None
    opponent_score: int | None
    kills: int | None
    deaths: int | None
    assists: int | None


@dataclass(frozen=True)
class MatchHistory:
    account_key: str
    display_name: str
    matches: tuple[HistoryMatch, ...]
    fetched_at: float
    authorization_id: str

    def dumps(self):
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def loads(cls, body):
        value = json.loads(body)
        value['matches'] = tuple(HistoryMatch(**row) for row in value['matches'])
        return cls(**value)
