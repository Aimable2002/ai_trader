import json

from .config import Settings
from .models import IngestRequest, TimeframePack

ROLES = ("entry", "setup", "bias and key levels")


def _number(value: float) -> str:
    return format(value, ".10g")


def format_timeframe(pack: TimeframePack, indicator_keys: list[str]) -> str:
    rows = ["time,open,high,low,close," + ",".join(indicator_keys)]
    for index, candle in enumerate(pack.candles):
        values = [candle.open, candle.high, candle.low, candle.close]
        values += [pack.indicators[key][index] for key in indicator_keys]
        rows.append(candle.open_time.strftime("%Y-%m-%dT%H:%M") + "," + ",".join(_number(v) for v in values))
    return "\n".join(rows)


def _active_block(active: list[dict]) -> str:
    if not active:
        return "none"
    return "\n".join(
        f"- id={s['id']} {s['direction']} status={s['lifecycle_status']} zone={_number(s['zone_low'])}-{_number(s['zone_high'])} "
        f"entry={_number(s['entry_price'])} stop={_number(s['stop_loss'])} "
        f"target={'none' if s['target'] is None else _number(s['target'])} issued={s['prediction_time'].strftime('%Y-%m-%dT%H:%M')}"
        for s in active
    )


def _lessons_block(lessons: list[dict]) -> str:
    if not lessons:
        return "none"
    return "\n".join(f"- id={l['id']}: {l['candidate_lesson']} (applies when: {l['conditions']})" for l in lessons)


def build_inference_messages(
    settings: Settings,
    req: IngestRequest,
    ordered_codes: list[str],
    active: list[dict],
    lessons: list[dict],
) -> list[dict]:
    packs = {pack.timeframe: pack for pack in req.timeframes}
    keys = sorted(settings.context_versions[req.context_version].indicators)
    sections = []
    for code, role in reversed(list(zip(ordered_codes, ROLES))):
        pack = packs[code]
        sections.append(
            f"## {code} - role: {role} ({len(pack.candles)} closed candles, oldest first)\n{format_timeframe(pack, keys)}"
        )
    user = (
        f"Instrument: {req.instrument}\n"
        f"Decision time (UTC): {req.trigger_candle_time.strftime('%Y-%m-%dT%H:%M')}\n\n"
        + "\n\n".join(sections)
        + f"\n\nActive signals:\n{_active_block(active)}"
        + f"\n\nValidated lessons for these conditions:\n{_lessons_block(lessons)}"
    )
    return [
        {"role": "system", "content": settings.prompts["inference"]},
        {"role": "user", "content": user},
    ]


def build_json_messages(system_prompt: str, payload: dict) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, default=str, indent=1)},
    ]
