"""Run a due routine through the existing agent loop."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from yata.agent.loop import run_agent, seal_open_tool_calls
from yata.confirm.gate import ConfirmationGate
from yata.llm.types import LLMMessage, LLMProvider, ProviderError
from yata.memory.store import MemoryStore, clip_title
from yata.prompts import build_system_prompt
from yata.routines.repository import Routine, RoutineRepository, RoutineRun
from yata.routines.schedule import ScheduleError, next_run, resolve_schedule
from yata.tools.base import ToolContextFactory
from yata.tools.policy import ToolPolicy
from yata.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_INTERRUPT = "サーバーが再起動したため、実行中のルーティンは中断しました。次の時刻にやり直します。"


class RoutineService:
    def __init__(
        self,
        *,
        memory: MemoryStore,
        routines: RoutineRepository,
        router: object,
        registry: ToolRegistry,
        gate: ConfirmationGate,
        browser: object,
        artifacts_dir: object,
        allow_private_urls: bool,
        max_steps: int,
        confirm_timeout: float,
        default_timezone: str,
    ):
        self.memory = memory
        self.routines = routines
        self.router = router
        self.registry = registry
        self.gate = gate
        self.browser = browser
        self.artifacts_dir = artifacts_dir
        self.allow_private_urls = allow_private_urls
        self.max_steps = max_steps
        self.confirm_timeout = confirm_timeout
        self.default_timezone = default_timezone
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create(
        self,
        *,
        name: str,
        prompt: str,
        model_id: str,
        preset: str | None = None,
        schedule: str | None = None,
        schedule_kind: str | None = None,
        timezone: str | None = None,
        now: datetime | None = None,
    ) -> Routine:
        zone = timezone or self.default_timezone
        kind, expression = resolve_schedule(
            preset=preset,
            schedule=schedule,
            schedule_kind=schedule_kind,
            zone=zone,
        )
        clean_name = name.strip()
        clean_prompt = prompt.strip()
        if not clean_name or not clean_prompt:
            raise ScheduleError("名前と指示を入れてください。")
        conversation = self.memory.create_conversation(model_id, title=clip_title(f"ルーティン: {clean_name}", 40))
        return self.routines.insert(
            name=clean_name,
            prompt=clean_prompt,
            schedule_kind=kind,
            schedule=expression,
            timezone=zone,
            model_id=model_id,
            conversation_id=conversation.id,
            now=now,
        )

    async def recover(self) -> None:
        interrupted = self.routines.interrupt_open_runs(_INTERRUPT)
        for run in interrupted:
            if self.memory.get_conversation(run.conversation_id) is None:
                continue
            self.memory.add_message(
                run.conversation_id,
                LLMMessage(role="assistant", content=_INTERRUPT),
            )

    async def run_due(self, now: datetime | None = None) -> list[str]:
        moment = now or datetime.now(UTC)
        launched: list[str] = []
        for routine in self.routines.due_routines(moment):
            try:
                nxt = next_run(routine.schedule_kind, routine.schedule, routine.timezone, moment)
            except ScheduleError:
                logger.exception("routine %s has an invalid schedule", routine.id)
                continue
            run = self.routines.claim(routine.id, moment, nxt)
            if run is None:
                continue
            self._tasks[run.id] = asyncio.create_task(self._guard(routine, run))
            launched.append(routine.id)
        return launched

    async def wait_for(self, routine_ids: list[str] | None = None) -> None:
        pending = [
            task
            for run_id, task in self._tasks.items()
            if not task.done() and (routine_ids is None or self._run_matches(run_id, routine_ids))
        ]
        if pending:
            await asyncio.gather(*pending)

    async def cancel(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _run_matches(self, run_id: str, routine_ids: list[str]) -> bool:
        run = self.routines.get_run(run_id)
        return run is not None and run.routine_id in routine_ids

    async def _guard(self, routine: Routine, run: RoutineRun) -> None:
        try:
            await self._execute(routine, run)
        except asyncio.CancelledError:
            self.routines.finish_run(run.id, status="error", snippet="サーバー停止のため中断しました。")
            raise
        except Exception as exc:
            logger.exception("routine %s failed", routine.id)
            current = self.routines.get_run(run.id)
            if current and current.status in {"running", "waiting_confirmation"}:
                self.routines.finish_run(
                    run.id,
                    status="error",
                    snippet=f"ルーティンの実行に失敗しました: {exc}",
                )

    async def _execute(self, routine: Routine, run: RoutineRun) -> None:
        status = "ok"
        snippet = ""
        fresh = self.routines.get(routine.id) or routine
        conversation_id = self._ensure_conversation(fresh)
        messages: list[LLMMessage] = []
        base_len = 0
        try:
            try:
                provider, upstream = self._resolve(fresh.model_id)
            except ProviderError as exc:
                status = "error"
                snippet = str(exc)
                self.memory.add_message(conversation_id, LLMMessage(role="assistant", content=snippet))
                return

            self.memory.add_message(conversation_id, LLMMessage(role="user", content=fresh.prompt))
            messages = [LLMMessage(role="system", content=build_system_prompt(self.memory.list_facts()))]
            messages.extend(item.to_llm() for item in self.memory.list_messages(conversation_id))
            base_len = len(messages)
            ctx = ToolContextFactory(
                memory=self.memory,
                browser=self.browser,
                artifacts_dir=self.artifacts_dir,
                allow_private_urls=self.allow_private_urls,
            ).for_conversation(conversation_id)
            async for event in run_agent(
                messages=messages,
                provider=provider,
                model=upstream,
                registry=self.registry,
                policy=ToolPolicy(),
                gate=self.gate,
                ctx=ctx,
                max_steps=self.max_steps,
                confirm_timeout=self.confirm_timeout,
            ):
                if event.type == "confirmation_required":
                    arguments = event.data.get("arguments") or {}
                    if not isinstance(arguments, dict):
                        arguments = {}
                    self.routines.mark_waiting(
                        run.id,
                        summary=str(event.data.get("summary") or "確認が必要です。"),
                        confirmation_id=str(event.data.get("request_id") or ""),
                        tool=str(event.data.get("tool") or ""),
                        risk=str(event.data.get("risk") or ""),
                        arguments=arguments,
                    )
                elif event.type == "answer":
                    snippet = str(event.data.get("content") or "")
                elif event.type == "error":
                    status = "error"
                    snippet = str(event.data.get("message") or snippet)
                elif event.type == "done" and not event.data.get("ok", True):
                    status = "error"
                    snippet = snippet or "ルーティンの実行に失敗しました。"
        except asyncio.CancelledError:
            status = "error"
            snippet = "サーバー停止のため中断しました。"
            raise
        except Exception as exc:
            logger.exception("routine execute failed")
            status = "error"
            snippet = f"ルーティンの実行に失敗しました: {exc}"
        finally:
            if messages:
                seal_open_tool_calls(messages)
                for message in messages[base_len:]:
                    self.memory.add_message(conversation_id, message)
            if not snippet:
                snippet = "応答が空でした。"
            self.routines.finish_run(run.id, status=status, snippet=snippet)

    def _resolve(self, model_id: str) -> tuple[LLMProvider, str]:
        provider, upstream = self.router.resolve(model_id)
        return provider, upstream

    def _ensure_conversation(self, routine: Routine) -> str:
        if self.memory.get_conversation(routine.conversation_id) is not None:
            return routine.conversation_id
        created = self.memory.create_conversation(
            routine.model_id,
            title=clip_title(f"ルーティン: {routine.name}", 40),
        )
        self.routines.replace_conversation(routine.id, created.id)
        return created.id
