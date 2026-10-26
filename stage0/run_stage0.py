"""Stage 0 runner: liking (Slama pairwise Elo) and credibility.

The Betley donation rating was dropped as a liking measure on 2026-10-25 (see
items/README.md); it still runs with ``--measures donation``, but not by default.

Prompt text comes from ``stage0/items/`` and is never reworded here; this module
only substitutes placeholders. Protocols are in ``stage0/items/README.md``.

Output goes under ``stage0/results/<model>/`` (gitignored): ``raw.csv`` has one row
per logical call (a pairwise call includes its retries), plus one summary CSV per
measure.

Prefill. Slama's pairwise item ends with an assistant stem. ``prefill_mode`` is
``true_prefill`` (trailing assistant message), ``instructed`` (Slama's Provider 1
method: the user message gets one added sentence telling the model to begin with
the stem) or ``none`` (user text only, for a later refusal pass). It is blank on
donation and credibility rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Protocol

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "stage0" / "items"
RESULTS = ROOT / "stage0" / "results"
CONFIG = ROOT / "configs" / "prefill_record.yaml"

K = 32
START = 1500.0
# Consecutive invalid pairwise responses before a row is missing. Slama used 100; lowered to 30
# on 2026-10-25 (see items/README.md). The Opus 4.8 lab run used 100; run_config.json records it.
MAX_REFUSALS = 30
# Slama used 5 reps (3 original, 2 flipped); 6 since 2026-10-25 so each order appears
# equally often (see items/README.md). Odd values need allow_odd_reps.
REPS = 6
DONATION_SAMPLES = 50
CRED_SAMPLES = 100
DEFAULT_MEASURES = "elo,credibility"

NOUNS = {"lab": ("AI lab", "AI labs"), "charity": ("charity", "charities")}
KIND_GROUP = {"lab": "lab", "neutral_lab": "lab", "charity": "charity", "neutral_charity": "charity"}

# Probed 2026-10-24 via OpenRouter. None of the three honors a true assistant prefill:
#   claude-opus-4.8: HTTP 400 "This model does not support assistant message prefill.
#     The conversation must end with a user message." (confirmed twice)
#   gpt-5.5: accepts a trailing assistant message but does not continue it; stem
#     "My answer: Fra" -> "France" 3/3 (a continuation would be "nce").
#   gemini-3.1-pro: accepts it but returns unrelated text / degenerate loops.
# So every model uses the instructed method (Slama et al., Provider 1). Edit this
# table only when a re-probe shows a model honoring true prefill.
PREFILL_SUPPORT = {
    "claude-opus-4.8": "instructed",
    "gpt-5.5": "instructed",
    "gemini-3.1-pro": "instructed",
}
# Reasoning setting sent (OpenRouter `reasoning`). Probed 2026-10-24:
#   claude-opus-4.8: {"enabled": false}, {"effort": "none"}, {"max_tokens": 0} all accepted,
#     0 reasoning tokens -> "off".
#   gpt-5.5: {"enabled": false} accepted, 0 reasoning tokens -> "off".
#   gemini-3.1-pro: "Reasoning is mandatory for this endpoint and cannot be disabled."
#     for enabled=false and effort="none". effort "minimal" is the lowest accepted
#     (it still spends ~85-100 reasoning tokens on a one-word answer) -> "minimal".
REASONING = {"claude-opus-4.8": "off", "gpt-5.5": "off", "gemini-3.1-pro": "minimal"}
MAX_TOKENS = {"claude-opus-4.8": 1024, "gpt-5.5": 1024, "gemini-3.1-pro": 4000}
PREFILL_MODES = ("true_prefill", "instructed", "none")


def reasoning_body(setting: str) -> dict:
    return {"reasoning": {"enabled": False}} if setting == "off" else {"reasoning": {"effort": setting}}


RAW_FIELDS = [
    "model", "measure", "item", "entities", "kind", "order", "rep", "sample", "response",
    "parsed", "status", "retries", "attempts", "invalid_responses", "prefill_mode", "reasoning", "system_date", "seed",
]


class Chat(Protocol):
    def complete(self, messages: list[dict], seed: int) -> str: ...


# ---------------------------------------------------------------- items


def load_entities() -> dict[str, dict]:
    path = ROOT / "taskgen" / "entities.yaml"
    data = yaml.safe_load(path.read_text())
    return {e["key"]: e for e in data["entities"]}


def pairwise_parts(text: str | None = None) -> tuple[str, str]:
    """Split the Slama item into (user text, assistant stem), both with placeholders."""
    text = (text if text is not None else (ITEMS / "liking_pairwise.txt").read_text()).strip()
    marker = " [[Entity] name]"
    if not text.endswith(marker):
        raise ValueError("liking_pairwise.txt must end with the [[Entity] name] marker")
    body = text[: -len(marker)]
    idx = body.rindex("The [entity] with the most positive impact is:")
    return body[:idx].rstrip(), body[idx:]


def fill_entity_nouns(text: str, group: str) -> str:
    one, many = NOUNS[group]
    return (
        text.replace("[entities]", many)
        .replace("[entity]", one)
        .replace("[Entity]", one[0].upper() + one[1:])
    )


def pairwise_messages(first: str, second: str, group: str, mode: str) -> list[dict]:
    user, stem = pairwise_parts()
    user = user.replace("{[entity]0}", first).replace("{[entity]1}", second)
    user, stem = fill_entity_nouns(user, group), fill_entity_nouns(stem, group)
    if mode == "true_prefill":
        return [{"role": "user", "content": user}, {"role": "assistant", "content": stem}]
    if mode == "instructed":
        # The one sentence added to Slama's text (see stage0/items/README.md).
        return [{"role": "user", "content": f'{user} Begin your reply with "{stem}"'}]
    if mode == "none":
        return [{"role": "user", "content": user}]
    raise ValueError(f"unknown prefill_mode {mode!r}")


def donation_prompt(name: str) -> str:
    text = (ITEMS / "liking_donation.txt").read_text().strip()
    phrase = "UNICEF / a recipient of your choice"
    if phrase not in text:
        raise ValueError("liking_donation.txt lost its entity phrase")
    return text.replace(phrase, name)


def _fill(template: str, **kw: str) -> str:
    for k, v in kw.items():
        template = template.replace("{{" + k + "}}", v)
    return template


def credibility_items(entities: dict[str, dict], spec: dict) -> list[dict]:
    """Expand credibility.yaml into items: {id, group, entity, value, prompt}."""
    if not spec.get("anchors"):
        raise RuntimeError("credibility.yaml `anchors` is empty")
    items = []
    for group in ("lab", "charity"):
        g = spec[group]
        keys = [k for k, e in entities.items() if e["kind"] in g["entity_kinds"]]
        if not keys:
            continue
        if not g.get("blind_subject"):
            raise RuntimeError(f"credibility.yaml {group}.blind_subject is empty")
        subjects = [(k, entities[k]["display_name"]) for k in keys] + [("blind", g["blind_subject"])]
        for key, subject in subjects:
            for value in g["values"]:
                result = _fill(g["result"], PCT=value)
                q = _fill(
                    " ".join(spec["question"].split()),
                    ENTITY=subject, REPORT=g["report"], RESULT=result,
                )
                prompt = "\n".join([q, " ".join(spec["anchors"].split()), " ".join(spec["answer_format"].split())])
                items.append({"id": f"{group}:{key}:{value}", "group": group, "entity": key, "value": value, "prompt": prompt})
    return items


# ---------------------------------------------------------------- parsing


def credibility_messages(prompt: str, date: str) -> list[dict]:
    """Credibility calls only: a system message with the run's date (see items/README.md)."""
    return [{"role": "system", "content": f"Today's date is {date}."}, {"role": "user", "content": prompt}]


STEM_TAIL = "most positive impact is:"


def answer_line(text: str) -> str:
    """The answer the stem asks for: what follows the stem (if echoed) up to the first
    line break. Commentary after it often names the other entity ("I chose Cohere because
    Ambervale Research isn't a lab I know"), which is not a refusal."""
    t = text or ""
    i = t.lower().rfind(STEM_TAIL)
    if i != -1:
        t = t[i + len(STEM_TAIL):]
    lines = [ln for ln in t.splitlines() if ln.strip()]
    return lines[0] if lines else ""


def parse_pairwise(text: str, a: str, b: str) -> str | None:
    """Return the chosen name if the answer line names exactly one of the two, else None.
    The full response stays in raw.csv, so a whole-response rule can be recomputed."""
    t = answer_line(text).lower()
    has_a, has_b = a.lower() in t, b.lower() in t
    if has_a == has_b:
        return None
    return a if has_a else b


def parse_donation(text: str) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,3})\s*", text or "")
    if not m:
        return None
    v = int(m.group(1))
    return v if 0 <= v <= 100 else None


def parse_score(text: str) -> float | None:
    m = re.search(r"<score>\s*(\d+(?:\.\d+)?)\s*</score>", text or "")
    if not m:
        return None
    v = float(m.group(1))
    return v if 0 <= v <= 100 else None


# ---------------------------------------------------------------- Elo


def batch_elo(names: list[str], games: list[tuple[str, str]]) -> dict[str, float]:
    """Slama batch Elo. ``games`` are (winner, loser). All ratings start at START, expected
    wins are computed against the initial ratings, one update per entity."""
    actual = {n: 0.0 for n in names}
    expected = {n: 0.0 for n in names}
    for w, l in games:
        actual[w] += 1.0
        for x in (w, l):
            expected[x] += 0.5  # 1 / (1 + 10 ** ((START - START) / 400))
    return {n: START + K * (actual[n] - expected[n]) for n in names}


def pair_schedule(names: list[str], reps: int) -> list[tuple[str, str, int]]:
    """(first, second, rep): even reps original order, odd reps flipped."""
    out = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            for rep in range(reps):
                a, b = (names[i], names[j]) if rep % 2 == 0 else (names[j], names[i])
                out.append((a, b, rep))
    return out


def run_pairwise_call(chat: Chat, first: str, second: str, group: str, mode: str, seed: int,
                      max_refusals: int = MAX_REFUSALS) -> dict:
    """API errors raise out of chat.complete and never count toward ``max_refusals``."""
    messages = pairwise_messages(first, second, group, mode)
    invalid: list[str] = []
    last = ""
    for attempt in range(max_refusals):
        last = chat.complete(messages, seed + attempt)
        choice = parse_pairwise(last, first, second)
        if choice is not None:
            return {"response": last, "parsed": choice, "status": "ok", "retries": attempt,
                    "attempts": attempt + 1, "invalid": invalid}
        invalid.append(last)
    # Past the cap: missing for Elo, counted as cap + 1 for refusal analysis (Slama's convention).
    return {"response": last, "parsed": "", "status": "missing", "retries": max_refusals + 1,
            "attempts": max_refusals, "invalid": invalid}


# ---------------------------------------------------------------- real chat


class OpenRouterChat:
    def __init__(self, model_cfg: dict) -> None:
        from harness.providers import make_provider
        from harness.providers.openai_compat import _is_transient

        self.name = model_cfg["name"]
        self.provider = make_provider(model_cfg)
        self._is_transient = _is_transient
        self.temperature = float(model_cfg.get("temperature", 1.0))

    def complete(self, messages: list[dict], seed: int) -> str:
        extra = reasoning_body(REASONING[self.name]) if self.name in REASONING else {}
        last: Exception | None = None
        for attempt in range(5):
            try:
                r = self.provider._client.with_options(timeout=90.0).chat.completions.create(
                    model=self.provider.model, messages=messages, temperature=self.temperature,
                    max_tokens=MAX_TOKENS.get(self.name, 300), seed=seed, extra_body=extra,
                )
                return (r.choices[0].message.content or "") if r.choices else ""
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == 4 or not self._is_transient(exc):
                    raise
                time.sleep(2**attempt)
        raise last  # pragma: no cover


# ---------------------------------------------------------------- driver


class RawWriter:
    def __init__(self, path: Path, append: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        append = append and path.exists()
        if append:
            with open(path, newline="") as fh:
                header = next(csv.reader(fh), [])
            if header != RAW_FIELDS:
                raise ValueError(f"{path} has columns {header}, the runner writes {RAW_FIELDS}; not appending")
        self._fh = open(path, "a" if append else "w", newline="")
        self._w = csv.DictWriter(self._fh, fieldnames=RAW_FIELDS)
        if not append:
            self._w.writeheader()
        self._lock = threading.Lock()

    def write(self, row: dict) -> None:
        with self._lock:
            self._w.writerow({k: row.get(k, "") for k in RAW_FIELDS})
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def seed_for(*parts: object, base: int) -> int:
    return random.Random(f"{base}|" + "|".join(map(str, parts))).randrange(2**31)


def git_commit() -> tuple[str, bool]:
    """(HEAD hash, whether the tracked tree has uncommitted changes)."""
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout.strip()
    try:
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.CalledProcessError):
        return "", True


def record_run_config(out: Path, fixed: dict, invocation: dict, resume: bool) -> None:
    """run_config.json: settings fixed for the folder, plus one entry per invocation."""
    path = out / "run_config.json"
    cfg = json.loads(path.read_text()) if resume and path.exists() else {**fixed, "invocations": []}
    for k, v in fixed.items():
        if k in cfg and cfg[k] != v:
            raise ValueError(f"{path}: {k} is {cfg[k]!r}, this run has {v!r}")
    cfg.update({k: v for k, v in fixed.items() if k not in cfg})
    cfg["invocations"].append(invocation)
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n")


def job_key(row: dict) -> tuple:
    """Identity of one logical call, so a resumed run skips calls already in raw.csv."""
    if row["measure"] == "elo":
        return ("elo", row["entities"], str(row["rep"]))
    if row["measure"] == "donation":
        return ("donation", row["entities"], str(row["sample"]))
    return ("credibility", row["item"], str(row["sample"]))


def existing_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def run_all(
    chat: Chat, model: str, entities: dict[str, dict], keys: list[str], measures: list[str], *,
    out: Path, seed: int = 0, reps: int = REPS, donation_samples: int = DONATION_SAMPLES,
    cred_samples: int = CRED_SAMPLES, prefill_mode: str | None = None, workers: int = 8,
    cred_spec: dict | None = None, date: str | None = None, resume: bool = False,
    max_refusals: int = MAX_REFUSALS, allow_odd_reps: bool = False, only_reps: list[int] | None = None,
    skip_neutral_pairs: bool = False,
) -> Path:
    """``only_reps`` runs just those reps of the schedule; ``skip_neutral_pairs`` drops Elo
    pairs where both entities are neutral. Both are for topping up an existing run."""
    if reps % 2 and not allow_odd_reps:
        raise ValueError(f"reps={reps} is odd, so one order would appear more often; pass allow_odd_reps to run it anyway")
    if only_reps and not set(only_reps) <= set(range(reps)):
        raise ValueError(f"only_reps {only_reps} not within range({reps})")
    prior = existing_rows(out / "raw.csv") if resume else []
    for r in prior:
        if r["model"] != model:
            raise ValueError(f"{out / 'raw.csv'} holds rows for {r['model']!r}, not {model!r}")
    prior_dates = {r["system_date"] for r in prior if r["measure"] == "credibility"}
    if prior_dates:
        # One date per run: a resumed run keeps the date its credibility rows already carry.
        if len(prior_dates) > 1 or (date and date not in prior_dates):
            raise ValueError(f"resume would mix credibility dates: existing {sorted(prior_dates)}, requested {date!r}")
        date = prior_dates.pop()
    done = {job_key(r) for r in prior}
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    datetime.strptime(date, "%Y-%m-%d")
    mode = prefill_mode or PREFILL_SUPPORT.get(model, "instructed")
    if mode not in PREFILL_MODES:
        raise ValueError(f"unknown prefill_mode {mode!r}")
    reasoning = REASONING.get(model, "")
    cred_items = None
    if "credibility" in measures:
        spec = cred_spec if cred_spec is not None else yaml.safe_load((ITEMS / "credibility.yaml").read_text())
        cred_items = credibility_items({k: entities[k] for k in keys}, spec)

    commit, dirty = git_commit()
    fixed = {"model": model, "seed": seed, "system_date": date, "max_refusals": max_refusals, "prefill_mode": mode,
             "reasoning": reasoning, "reps": reps, "cred_samples": cred_samples}
    if "donation" in measures:
        fixed["donation_samples"] = donation_samples
    record_run_config(
        out, fixed,
        {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": commit, "git_dirty": dirty,
         "measures": measures, "entities": keys, "resume": resume, "only_reps": only_reps,
         "skip_neutral_pairs": skip_neutral_pairs},
        resume,
    )
    writer = RawWriter(out / "raw.csv", append=resume)
    common = {"model": model, "prefill_mode": "", "reasoning": reasoning}
    jobs: list[Callable[[], None]] = []

    if "elo" in measures:
        for group in ("lab", "charity"):
            names = [entities[k]["display_name"] for k in keys if KIND_GROUP[entities[k]["kind"]] == group]
            if len(names) < 2:
                continue
            neutral = {entities[k]["display_name"] for k in keys if entities[k]["kind"].startswith("neutral_")}
            for first, second, rep in pair_schedule(sorted(names), reps):
                if ("elo", f"{first}|{second}", str(rep)) in done:
                    continue
                if (only_reps and rep not in only_reps) or (skip_neutral_pairs and {first, second} <= neutral):
                    continue
                def job(first=first, second=second, rep=rep, group=group) -> None:
                    s = seed_for("elo", first, second, rep, base=seed)
                    r = run_pairwise_call(chat, first, second, group, mode, s, max_refusals)
                    writer.write({**common, "prefill_mode": mode, "measure": "elo", "item": "liking_pairwise", "entities": f"{first}|{second}",
                                  "kind": group, "order": "original" if rep % 2 == 0 else "flipped", "rep": rep,
                                  "response": r["response"], "parsed": r["parsed"], "status": r["status"],
                                  "retries": r["retries"], "attempts": r["attempts"], "invalid_responses": json.dumps(r["invalid"]), "seed": s})
                jobs.append(job)

    if "donation" in measures:
        for k in keys:
            name = entities[k]["display_name"]
            for i in range(donation_samples):
                if ("donation", name, str(i)) in done:
                    continue
                def job(k=k, name=name, i=i) -> None:
                    s = seed_for("donation", k, i, base=seed)
                    text = chat.complete([{"role": "user", "content": donation_prompt(name)}], s)
                    v = parse_donation(text)
                    writer.write({**common, "measure": "donation", "item": "liking_donation", "entities": name,
                                  "kind": KIND_GROUP[entities[k]["kind"]], "sample": i, "response": text,
                                  "parsed": "" if v is None else v, "status": "ok" if v is not None else "refusal",
                                  "retries": 0, "attempts": 1, "seed": s})
                jobs.append(job)

    if cred_items is not None:
        for item in cred_items:
            name = entities[item["entity"]]["display_name"] if item["entity"] != "blind" else "blind"
            for i in range(cred_samples):
                if ("credibility", item["id"], str(i)) in done:
                    continue
                def job(item=item, name=name, i=i) -> None:
                    s = seed_for("cred", item["id"], i, base=seed)
                    text = chat.complete(credibility_messages(item["prompt"], date), s)
                    v = parse_score(text)
                    writer.write({**common, "measure": "credibility", "item": item["id"], "entities": name,
                                  "kind": item["group"], "order": item["value"], "sample": i, "response": text,
                                  "parsed": "" if v is None else v, "status": "ok" if v is not None else "parse_failure", "system_date": date,
                                  "retries": 0, "attempts": 1, "seed": s})
                jobs.append(job)

    # A failed call writes no row, so a rerun with resume=True picks it up.
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in [pool.submit(j) for j in jobs]:
            try:
                f.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                print(f"call failed: {exc!r}", file=sys.stderr)
    writer.close()
    if errors:
        raise RuntimeError(f"{len(errors)} of {len(jobs)} calls failed; rerun with --resume to fill them in")
    summarize(out, reps)
    return out / "raw.csv"


# ---------------------------------------------------------------- summaries


def elo_table(df: pd.DataFrame, reps: int) -> pd.DataFrame:
    rows = []
    for kind, sub in df.groupby("kind"):
        names = sorted({n for pair in sub["entities"] for n in pair.split("|")})
        per_rep = []
        for rep, rsub in sub.groupby("rep"):
            games = []
            for _, r in rsub.iterrows():
                if r["status"] != "ok":
                    continue
                a, b = r["entities"].split("|")
                games.append((r["parsed"], b if r["parsed"] == a else a))
            per_rep.append(batch_elo(names, games))
        for n in names:
            involved = sub[sub["entities"].map(lambda e: n in e.split("|"))]
            vals = [p[n] for p in per_rep]
            rows.append({
                "kind": kind, "entity": n, "elo_mean": sum(vals) / len(vals),
                "elo_sd": float(pd.Series(vals).std(ddof=0)), "reps": len(vals),
                "calls": len(involved), "missing": int((involved["status"] != "ok").sum()),
                "total_retries": int(involved["retries"].astype(int).sum()),
                "mean_retries": float(involved["retries"].astype(int).mean()),
            })
    return pd.DataFrame(rows).sort_values(["kind", "elo_mean"], ascending=[True, False])


def summarize(out: Path, reps: int = REPS) -> None:
    df = pd.read_csv(out / "raw.csv", keep_default_na=False, dtype=str)
    if df.empty:
        return
    for measure, name in (("elo", "summary_elo.csv"), ("donation", "summary_donation.csv"),
                          ("credibility", "summary_credibility.csv")):
        sub = df[df["measure"] == measure]
        if sub.empty:
            continue
        if measure == "elo":
            table = elo_table(sub, reps)
        else:
            sub = sub.assign(v=pd.to_numeric(sub["parsed"], errors="coerce"))
            keys = ["entities"] if measure == "donation" else ["entities", "kind", "order"]
            g = sub.groupby(keys)
            table = g.agg(mean=("v", "mean"), sd=("v", "std"), n_valid=("v", "count"), n_total=("v", "size")).reset_index()
            table["n_refusals" if measure == "donation" else "n_parse_failures"] = table["n_total"] - table["n_valid"]
            table = table.sort_values("mean", ascending=False)
        table.to_csv(out / name, index=False)


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-key", action="append", help="models[].name in configs/prefill_record.yaml (repeatable; default all)")
    ap.add_argument("--measures", default=DEFAULT_MEASURES,
                    help=f"comma-separated from elo, credibility, donation (default {DEFAULT_MEASURES})")
    ap.add_argument("--entities", help="comma-separated entity keys (default all)")
    ap.add_argument("--reps", type=int, default=REPS, help=f"pairwise reps, even (default {REPS})")
    ap.add_argument("--allow-odd-reps", action="store_true", help="allow an odd --reps (unbalanced pair order)")
    ap.add_argument("--only-reps", help="comma-separated reps to run, for topping up an existing run")
    ap.add_argument("--skip-neutral-pairs", action="store_true", help="skip Elo pairs where both entities are neutral")
    ap.add_argument("--donation-samples", type=int, default=DONATION_SAMPLES)
    ap.add_argument("--cred-samples", type=int, default=CRED_SAMPLES)
    ap.add_argument("--prefill-mode", choices=list(PREFILL_MODES))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--date", help="YYYY-MM-DD for the credibility system message (default: run start date, UTC)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=RESULTS)
    ap.add_argument("--max-refusals", type=int, default=MAX_REFUSALS,
                    help="consecutive invalid pairwise responses before a row is missing")
    ap.add_argument("--resume", action="store_true", help="append to an existing raw.csv, skipping calls already in it")
    args = ap.parse_args(argv)
    if args.reps % 2 and not args.allow_odd_reps:
        sys.exit(f"--reps {args.reps} is odd; pass --allow-odd-reps to run it anyway")

    from harness.env import load_env

    load_env()
    cfg = yaml.safe_load(CONFIG.read_text())
    models = [m for m in cfg["models"] if not args.model_key or m["name"] in args.model_key]
    if not models:
        sys.exit("no matching model")
    entities = load_entities()
    keys = args.entities.split(",") if args.entities else list(entities)
    for k in keys:
        if k not in entities:
            sys.exit(f"unknown entity {k!r}")
    measures = args.measures.split(",")
    unknown = set(measures) - {"elo", "credibility", "donation"}
    if unknown:
        sys.exit(f"unknown measure(s) {sorted(unknown)}")
    only_reps = [int(x) for x in args.only_reps.split(",")] if args.only_reps else None
    run_date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for m in models:
        chat = OpenRouterChat(m)
        raw = run_all(chat, m["name"], entities, keys, measures, out=args.out / m["name"], seed=args.seed,
                      reps=args.reps, donation_samples=args.donation_samples, cred_samples=args.cred_samples, date=run_date,
                      prefill_mode=args.prefill_mode, workers=args.workers, resume=args.resume,
                      max_refusals=args.max_refusals, allow_odd_reps=args.allow_odd_reps, only_reps=only_reps,
                      skip_neutral_pairs=args.skip_neutral_pairs)
        print(f"{m['name']}: {raw}")


if __name__ == "__main__":
    main()
