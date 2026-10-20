"""Durable logical Agent state. Implementations must atomically commit ledgers + checkpoint."""

from contextlib import AbstractContextManager
from typing import Protocol


class AgentStore(Protocol):
    def import_version(self, kind: str, ref: str, document: dict) -> None: ...
    def version(self, kind: str, ref: str) -> dict: ...
    def publish(self, kind: str, ref: str, publisher: str, *, bundle=None) -> None: ...
    def disable(self, kind: str, ref: str) -> None: ...
    def context(self, actor: str, experiment_id: str, resources: list[str]) -> dict: ...
    def create(
        self,
        identity: str,
        actor: str,
        experiment_id: str,
        ref: str,
        bundle: dict,
        checkpoint: dict,
    ) -> dict: ...
    def load(self, actor: str, identity: str) -> dict: ...
    def exclusive(self, identity: str) -> AbstractContextManager: ...
    def authorize_worker(self, actor: str) -> None: ...
    def worker_candidates(
        self, actor: str, experiments: list[str], *, after: str = "", limit: int = 20
    ) -> list[dict]: ...
    def commit(
        self,
        run: dict,
        checkpoint: dict,
        event: dict,
        *,
        invocations=(),
        proposals=(),
        check_snapshot: bool = False,
    ) -> dict: ...
