import logging
from collections import defaultdict
from datetime import datetime

from .config import Settings
from .context import build_json_messages
from .llm import StructuredLLM
from .models import EvidenceSelection, ReflectionOutput, ValidationVerdict
from .repository import Repository, Scope

PRIMARY = "primary"
logger = logging.getLogger(__name__)


def count_results(cases: list[dict]) -> tuple[int, int]:
    return sum(c["result"] == "WIN" for c in cases), sum(c["result"] == "MISTAKE" for c in cases)


def flag_shared_exits(cases: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for case in cases:
        if case["exit_signal_id"] is not None:
            groups[case["exit_signal_id"]].append(case["id"])
    return [{**case, "shares_exit_with": [i for i in groups.get(case["exit_signal_id"], []) if i != case["id"]]} for case in cases]


def next_status(current: str, verdict: str, relevant_count: int) -> str:
    if verdict == "PROMOTE":
        return "VALIDATED" if relevant_count else current
    if verdict == "KEEP_CANDIDATE":
        return current
    return "REJECTED" if current == "CANDIDATE" else "RETIRED"


class MemoryService:
    def __init__(self, repo: Repository, llm: StructuredLLM, settings: Settings):
        self._repo = repo
        self._llm = llm
        self._settings = settings

    def retrieve(self, scope: Scope, at: datetime) -> list[dict]:
        return self._repo.validated_lessons(scope, at, self._settings.memory.lessons_per_call)

    def reflect_mistakes(self, scope: Scope, at: datetime) -> list[int]:
        created = []
        for mistake in self._repo.unreflected_mistakes(scope, PRIMARY):
            lesson_id = self._reflect(scope, mistake, at)
            if lesson_id:
                created.append(lesson_id)
        return created

    def _reflect(self, scope: Scope, mistake: dict, at: datetime) -> int | None:
        contrast = self._repo.resolved_cases(
            scope, PRIMARY, direction=mistake["direction"], correct=True, limit=self._settings.memory.contrast_cases
        )
        payload = {
            "conditions": {"instrument": scope.instrument, "timeframes": scope.timeframe_set, "context_version": scope.context_version, "model": scope.model_key},
            "mistake": {k: mistake[k] for k in ("signal_id", "direction", "zone_low", "zone_high", "entry_price", "stop_loss", "target", "exit_price", "exit_reason", "signed_move", "mfe", "mae", "rationale")},
            "correct_cases": contrast,
        }
        output = self._llm.ask("reflection", scope.model_key, build_json_messages(self._settings.prompts["reflection"], payload), ReflectionOutput)
        self._repo.mark_reflected(mistake["outcome_id"], at)
        if output.abstain:
            return None
        verified = self._repo.verify_cases(scope, PRIMARY, output.cited_signal_ids)
        return self._repo.insert_lesson(
            {
                "instrument": scope.instrument,
                "timeframe_set": scope.timeframe_set,
                "context_version": scope.context_version,
                "model_key": scope.model_key,
                "status": "CANDIDATE",
                "origin_signal_id": mistake["signal_id"],
                "observed_fact": output.observed_fact,
                "hypothesis": output.hypothesis,
                "candidate_lesson": output.candidate_lesson,
                "conditions": output.conditions,
                "cited_signal_ids": [case["id"] for case in verified],
                "model_confidence": output.model_confidence,
                "created_at": at,
            }
        )

    def validate_due(self, scope: Scope, at: datetime) -> list[int]:
        memory = self._settings.memory
        judged = []
        for lesson in self._repo.judgeable_lessons(scope):
            since = lesson["last_judged_at"] or lesson["created_at"]
            new_cases = self._repo.resolved_cases(scope, PRIMARY, since=since, limit=memory.evidence_cases_cap)
            if len(new_cases) >= memory.validation_cadence_new_cases:
                self._judge(scope, lesson, new_cases, at)
                judged.append(lesson["id"])
        return judged

    def _judge(self, scope: Scope, lesson: dict, new_cases: list[dict], at: datetime) -> None:
        prompts = self._settings.prompts
        lesson_view = {k: lesson[k] for k in ("id", "candidate_lesson", "conditions", "hypothesis", "status")}
        selection = self._llm.ask(
            "evidence_selection",
            scope.model_key,
            build_json_messages(prompts["evidence_selection"], {"lesson": lesson_view, "resolved_signals": new_cases}),
            EvidenceSelection,
        )
        chosen = set(selection.relevant_signal_ids)
        relevant = flag_shared_exits([case for case in new_cases if case["id"] in chosen])
        right, wrong = count_results(relevant)
        origin_ids = [*lesson["cited_signal_ids"], lesson["origin_signal_id"]]
        payload = {
            "lesson": lesson_view,
            "verified_counts": {"right": right, "wrong": wrong, "relevant_cases": len(relevant)},
            "relevant_cases_after_creation": relevant,
            "originating_cases_not_independent": self._repo.verify_cases(scope, PRIMARY, origin_ids),
        }
        verdict = self._llm.ask("validation", scope.model_key, build_json_messages(prompts["validation"], payload), ValidationVerdict)
        status = next_status(lesson["status"], verdict.verdict, len(relevant))
        promoted_now = status == "VALIDATED" and lesson["status"] == "CANDIDATE"
        self._repo.insert_verdict(
            {
                "lesson_id": lesson["id"],
                "verdict": verdict.verdict,
                "model_confidence": verdict.model_confidence,
                "reasoning": verdict.reasoning,
                "verified_right": right,
                "verified_wrong": wrong,
                "evidence_signal_ids": [case["id"] for case in relevant],
                "judged_at": at,
            }
        )
        self._repo.apply_verdict(lesson["id"], status, at if promoted_now else None, at)
