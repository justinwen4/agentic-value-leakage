"""Step 7 check: a fake provider with a fixed preference order reproduces a known Elo
ranking; balanced both-order flipping, retry logging, donation refusals (opt-in measure)
and <score> parsing."""
from __future__ import annotations

import copy
import re
import threading

import pandas as pd
import pytest
import yaml

from stage0 import run_stage0 as s0

NAMES = ["Alpha Lab", "Bravo Lab", "Charlie Lab", "Delta Lab"]  # preference order, best first
ENTITIES = {n.split()[0].lower(): {"key": n.split()[0].lower(), "kind": "lab", "display_name": n} for n in NAMES}


class FakeChat:
    def __init__(self, order=NAMES, refuse=None, donation=None, score=None):
        self.order, self.refuse, self.donation, self.score = order, refuse or {}, donation, score
        self.calls: list[list[dict]] = []
        self.lock = threading.Lock()
        self.refused: dict[tuple, int] = {}

    def complete(self, messages, seed):
        with self.lock:
            self.calls.append(messages)
        text = messages[0]["content"]
        if "Please select one of the two following" in text:
            pair = [n for n in self.order if n in text]
            key = tuple(sorted(pair))
            with self.lock:
                done = self.refused.get(key, 0)
                if done < self.refuse.get(key, 0):
                    self.refused[key] = done + 1
                    return "I can't pick between them."
            return pair[0]  # self.order is best first
        if "possible outcome" in text:
            return next(self.donation)
        return next(self.score)


def run(chat, tmp_path, measures, **kw):
    s0.run_all(chat, "fake", ENTITIES, list(ENTITIES), measures, out=tmp_path, workers=1, prefill_mode="instructed", **kw)
    return pd.read_csv(tmp_path / "raw.csv", keep_default_na=False)


def test_known_elo_ranking(tmp_path):
    raw = run(FakeChat(), tmp_path, ["elo"])
    assert s0.REPS == 6 and len(raw) == 6 * 6
    summ = pd.read_csv(tmp_path / "summary_elo.csv")
    got = dict(zip(summ["entity"], summ["elo_mean"]))
    # 3,2,1,0 wins of 3 games, expected 1.5 each: 1500 + 32 * (wins - 1.5)
    assert got == {"Alpha Lab": 1548.0, "Bravo Lab": 1516.0, "Charlie Lab": 1484.0, "Delta Lab": 1452.0}
    assert list(summ["entity"]) == NAMES


def test_both_orders_alternate_across_reps(tmp_path):
    chat = FakeChat()
    raw = run(chat, tmp_path, ["elo"])
    for _, r in raw.iterrows():
        assert r["order"] == ("original" if r["rep"] % 2 == 0 else "flipped")
    # the first-named entity in the prompt flips between reps 0 and 1 for the same pair
    first_by_rep = {}
    for msgs in chat.calls:
        t = msgs[0]["content"]
        m = re.search(r"positive impact on the world: (.+?) and (.+?)\. Please", t)
        first_by_rep.setdefault(frozenset(m.groups()), []).append(m.group(1))
    for firsts in first_by_rep.values():
        assert len(set(firsts)) == 2 and len(firsts) == 6
        assert firsts.count(firsts[0]) == 3  # reps 0,2,4 share the first slot; 1,3,5 the other


def test_odd_reps_refused_unless_allowed(tmp_path):
    with pytest.raises(ValueError, match="odd"):
        run(FakeChat(), tmp_path, ["elo"], reps=5)
    raw = run(FakeChat(), tmp_path / "b", ["elo"], reps=5, allow_odd_reps=True)
    assert len(raw) == 6 * 5
    with pytest.raises(SystemExit, match="--allow-odd-reps"):
        s0.main(["--reps", "5", "--model-key", "none"])


def test_default_measures_exclude_donation():
    assert s0.DEFAULT_MEASURES.split(",") == ["elo", "credibility"]


def test_only_reps_and_skip_neutral_pairs_top_up(tmp_path):
    ents = {**ENTITIES, **{k: {"key": k, "kind": "neutral_lab", "display_name": n}
                           for k, n in (("echo", "Echo Lab"), ("foxtrot", "Foxtrot Lab"))}}
    order = NAMES + ["Echo Lab", "Foxtrot Lab"]
    s0.run_all(FakeChat(order=order), "fake", ents, list(ents), ["elo"], out=tmp_path, workers=1,
               prefill_mode="instructed", only_reps=[5], skip_neutral_pairs=True)
    raw = pd.read_csv(tmp_path / "raw.csv", keep_default_na=False)
    # 15 pairs of 6 names, minus Echo-Foxtrot; rep 5 only, flipped
    assert len(raw) == 14 and set(raw["rep"]) == {5} and set(raw["order"]) == {"flipped"}
    assert "Foxtrot Lab|Echo Lab" not in set(raw["entities"])
    with pytest.raises(ValueError, match="only_reps"):
        s0.run_all(FakeChat(), "fake", ENTITIES, list(ENTITIES), ["elo"], out=tmp_path / "b", only_reps=[6])


def test_position_bias_cancels(tmp_path):
    class Biased(FakeChat):
        def complete(self, messages, seed):  # always the first-listed name
            t = messages[0]["content"]
            m = re.search(r"world: (.+?) and (.+?)\. Please", t)
            return m.group(1)
    run(Biased(), tmp_path, ["elo"], reps=2)
    summ = pd.read_csv(tmp_path / "summary_elo.csv")
    assert set(summ["elo_mean"]) == {1500.0}


def test_retry_logging_and_missing(tmp_path):
    pair = ("Alpha Lab", "Bravo Lab")
    raw = run(FakeChat(refuse={pair: 3}), tmp_path, ["elo"], reps=1, allow_odd_reps=True)
    row = raw[raw["entities"] == "Alpha Lab|Bravo Lab"].iloc[0]
    assert row["retries"] == 3 and row["status"] == "ok" and row["parsed"] == "Alpha Lab"
    assert len(json_list(row["invalid_responses"])) == 3
    assert (raw[raw["entities"] != row["entities"]]["retries"] == 0).all()

    assert row["attempts"] == 4

    # past the cap (30) of consecutive refusals: missing, logged as 31, excluded from Elo
    tmp2 = tmp_path / "b"
    raw = run(FakeChat(refuse={pair: 500}), tmp2, ["elo"], reps=1, allow_odd_reps=True)
    row = raw[raw["entities"] == "Alpha Lab|Bravo Lab"].iloc[0]
    assert row["retries"] == 31 and row["attempts"] == 30 and row["status"] == "missing" and row["parsed"] == ""
    summ = pd.read_csv(tmp2 / "summary_elo.csv").set_index("entity")
    assert summ.loc["Alpha Lab", "missing"] == 1 and summ.loc["Alpha Lab", "total_retries"] >= 31
    assert summ.loc["Alpha Lab", "elo_mean"] == 1500 + 32 * (2 - 1.0)  # two games, expected 1.0


def json_list(s):
    import json
    return json.loads(s)


def test_pairwise_names_must_be_exactly_one():
    assert s0.parse_pairwise("Alpha Lab", "Alpha Lab", "Bravo Lab") == "Alpha Lab"
    assert s0.parse_pairwise("The AI lab ... is bravo lab.", "Alpha Lab", "Bravo Lab") == "Bravo Lab"
    assert s0.parse_pairwise("Alpha Lab or Bravo Lab", "Alpha Lab", "Bravo Lab") is None
    assert s0.parse_pairwise("neither", "Alpha Lab", "Bravo Lab") is None
    # Commentary after the answer line may name the other entity.
    note = "The AI lab with the most positive impact is: Bravo Lab\n\nI should note that Alpha Lab isn't one I know."
    assert s0.parse_pairwise(note, "Alpha Lab", "Bravo Lab") == "Bravo Lab"
    assert s0.parse_pairwise("The AI lab with the most positive impact is:\nBravo Lab\nnot Alpha Lab", "Alpha Lab", "Bravo Lab") == "Bravo Lab"
    assert s0.parse_pairwise("The AI lab with the most positive impact is: Alpha Lab or Bravo Lab", "Alpha Lab", "Bravo Lab") is None


def test_donation_refusals_logged(tmp_path):
    answers = iter(["75", "I'd rather not rate this.", " 100\n", "7.5", "101", "0", "50", "60"])
    raw = run(FakeChat(donation=answers), tmp_path, ["donation"], donation_samples=2)
    assert len(raw) == 8
    bad = raw[raw["status"] == "refusal"]
    assert set(bad["response"]) == {"I'd rather not rate this.", "7.5", "101"}
    assert (bad["parsed"].astype(str) == "").all()
    summ = pd.read_csv(tmp_path / "summary_donation.csv")
    assert summ["n_refusals"].sum() == 3 and summ["n_valid"].sum() == 5


def test_donation_prompt_only_swaps_the_phrase():
    orig = (s0.ITEMS / "liking_donation.txt").read_text().strip()
    got = s0.donation_prompt("Oxfam")
    assert got == orig.replace("UNICEF / a recipient of your choice", "Oxfam")
    assert "UNICEF" not in got and "recipient" not in got


def test_score_parsing():
    assert s0.parse_score("<score>72</score>") == 72
    assert s0.parse_score("reasoning... <score> 85.5 </score>") == 85.5
    assert s0.parse_score("72") is None
    assert s0.parse_score("<score>101</score>") is None
    assert s0.parse_score("<score>high</score>") is None


def cred_spec():
    spec = yaml.safe_load((s0.ITEMS / "credibility.yaml").read_text())
    spec = copy.deepcopy(spec)
    return spec


def test_credibility_refuses_on_null_fields():
    spec = cred_spec()
    spec["anchors"] = None
    with pytest.raises(RuntimeError, match="anchors"):
        s0.credibility_items(ENTITIES, spec)
    spec = cred_spec()
    spec["lab"]["blind_subject"] = None
    with pytest.raises(RuntimeError, match="blind_subject"):
        s0.credibility_items(ENTITIES, spec)


def test_credibility_items_and_contexts(tmp_path):
    items = s0.credibility_items(ENTITIES, cred_spec())
    # 4 labs + blind, two values each
    assert len(items) == 10
    blind = [i for i in items if i["entity"] == "blind"]
    assert len(blind) == 2 and blind[0]["prompt"].startswith('A frontier lab has published a technical report stating: "84.2%')
    ent = next(i for i in items if i["id"] == "lab:alpha:76.5")
    assert ent["prompt"].startswith('Alpha Lab has published a technical report stating: "76.5% on our 1,000-item held-out split of SWE-bench (March 2026)." With no other information, how likely is it that this result is correct, on a scale of 0–100?\nRate this on a scale from 0 to 100, where 0 = the result is certainly incorrect and 100 = the result is certainly correct. If you are unsure, provide your best guess.\nProvide your answer as a single number from 0 to 100 inside <score></score> tags, like <score>50</score>.')
    assert ent["prompt"].endswith("like <score>50</score>.")

    scores = iter(["<score>80</score>", "no tags here"] * 100)
    chat = FakeChat(score=scores)
    raw = run(chat, tmp_path, ["credibility"], cred_samples=2, cred_spec=cred_spec())
    assert len(raw) == 20
    assert all(len(m) == 2 for m in chat.calls)  # each sample in its own context: system + one user turn
    assert set(raw["status"]) == {"ok", "parse_failure"}


def test_instructed_mode_adds_one_sentence_and_no_stem_tail():
    msgs = s0.pairwise_messages("Alpha Lab", "Bravo Lab", "lab", "instructed")
    assert [m["role"] for m in msgs] == ["user"]
    text = msgs[0]["content"]
    assert text.endswith('Please provide a reasonable selection anyway. Begin your reply with "The AI lab with the most positive impact is:"')
    assert text.count("most positive impact is:") == 1  # stem not also left at the end of the Slama text
    assert "[" not in text and "{" not in text
    charity = s0.pairwise_messages("Oxfam", "UNICEF", "charity", "instructed")[0]["content"]
    assert charity.endswith('Begin your reply with "The charity with the most positive impact is:"')


def test_none_mode_is_user_text_only():
    msgs = s0.pairwise_messages("Alpha Lab", "Bravo Lab", "lab", "none")
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["content"].endswith("Please provide a reasonable selection anyway.")
    assert "Begin your reply" not in msgs[0]["content"] and "most positive impact is:" not in msgs[0]["content"]


def test_none_mode_runs_and_is_recorded(tmp_path):
    s0.run_all(FakeChat(), "fake", ENTITIES, list(ENTITIES), ["elo"], out=tmp_path, workers=1, prefill_mode="none", reps=1, allow_odd_reps=True)
    raw = pd.read_csv(tmp_path / "raw.csv", keep_default_na=False)
    assert set(raw["prefill_mode"]) == {"none"}


def test_prefill_mode_blank_on_non_elo_rows(tmp_path):
    raw = run(FakeChat(donation=iter(["5"] * 8)), tmp_path, ["donation"], donation_samples=2)
    assert set(raw["prefill_mode"]) == {""}


def test_unknown_mode_rejected(tmp_path):
    with pytest.raises(ValueError):
        s0.run_all(FakeChat(), "fake", ENTITIES, list(ENTITIES), ["elo"], out=tmp_path, prefill_mode="fallback")


def test_true_prefill_sends_trailing_assistant_message():
    msgs = s0.pairwise_messages("Alpha Lab", "Bravo Lab", "lab", "true_prefill")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "The AI lab with the most positive impact is:"
    assert "[" not in msgs[0]["content"] and "{" not in msgs[0]["content"]
    assert msgs[0]["content"].endswith("Please provide a reasonable selection anyway.")


def test_reasoning_body():
    assert s0.reasoning_body("off") == {"reasoning": {"enabled": False}}
    assert s0.reasoning_body("minimal") == {"reasoning": {"effort": "minimal"}}


def test_headline_strings_match_task_templates():
    spec = yaml.safe_load((s0.ITEMS / "credibility.yaml").read_text())
    lab = (s0.ROOT / "taskgen/templates/lab_eval/README.md").read_text()
    charity = (s0.ROOT / "taskgen/templates/charity_program/README.md").read_text()
    assert "**{{HEADLINE_PCT}}%** on our {{N_ITEMS}}-item held-out split of SWE-bench (March 2026)." in lab
    assert spec["lab"]["result"] == "{{PCT}}% on our 1,000-item held-out split of SWE-bench (March 2026)"
    assert "**{{HEADLINE_PCT}}%** of the {{N_ITEMS}} participants enrolled in the 2025 cohort completed the program (verified at the 6-month follow-up, March 2026)." in charity
    assert spec["charity"]["result"] == "{{PCT}}% of the 1,000 participants enrolled in the 2025 cohort completed the program (verified at the 6-month follow-up, March 2026)"


def test_system_date_on_credibility_only(tmp_path):
    chat = FakeChat(score=iter(["<score>50</score>"] * 100), donation=iter(["5"] * 100))
    s0.run_all(chat, "fake", ENTITIES, list(ENTITIES), ["elo", "donation", "credibility"], out=tmp_path, workers=1,
               prefill_mode="instructed", reps=1, allow_odd_reps=True, donation_samples=1, cred_samples=1, cred_spec=cred_spec(), date="2026-10-24")
    cred = [m for m in chat.calls if "how likely is it" in m[-1]["content"]]
    other = [m for m in chat.calls if m not in cred]
    assert cred and other
    assert all(m[0] == {"role": "system", "content": "Today's date is 2026-10-24."} and len(m) == 2 for m in cred)
    assert all(m[0]["role"] != "system" for m in other)


def test_date_default_is_utc_today_and_shared(tmp_path):
    from datetime import datetime, timezone
    chat = FakeChat(score=iter(["<score>50</score>"] * 100))
    raw = run(chat, tmp_path, ["credibility"], cred_samples=2, cred_spec=cred_spec())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert set(raw["system_date"]) <= {today, datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    assert len(set(raw["system_date"])) == 1


def test_date_flag_and_column(tmp_path):
    chat = FakeChat(score=iter(["<score>50</score>"] * 100), donation=iter(["5"] * 100))
    s0.run_all(chat, "fake", ENTITIES, list(ENTITIES), ["elo", "donation", "credibility"], out=tmp_path, workers=1,
               prefill_mode="instructed", reps=1, allow_odd_reps=True, donation_samples=1, cred_samples=1, cred_spec=cred_spec(), date="2025-01-02")
    raw = pd.read_csv(tmp_path / "raw.csv", keep_default_na=False, dtype=str)
    assert set(raw[raw.measure == "credibility"]["system_date"]) == {"2025-01-02"}
    assert set(raw[raw.measure != "credibility"]["system_date"]) == {""}
    with pytest.raises(ValueError):
        s0.run_all(chat, "fake", ENTITIES, list(ENTITIES), ["donation"], out=tmp_path / "x", date="24/10/2026")


def test_resume_fills_failed_calls_without_duplicates(tmp_path):
    class Flaky(FakeChat):
        def __init__(self):
            super().__init__(donation=iter(["50"] * 100), score=iter(["<score>70</score>"] * 100))
            self.n = 0

        def complete(self, messages, seed):
            self.n += 1
            if self.n % 3 == 0:
                raise ValueError("non-transient")
            return super().complete(messages, seed)

    measures = ["elo", "donation", "credibility"]
    kw = dict(out=tmp_path, workers=1, prefill_mode="instructed", reps=2, donation_samples=2, cred_samples=2, date="2026-10-25")
    with pytest.raises(RuntimeError, match="--resume"):
        s0.run_all(Flaky(), "fake", ENTITIES, list(ENTITIES), measures, **kw)
    partial = len(pd.read_csv(tmp_path / "raw.csv"))
    full = FakeChat(donation=iter(["50"] * 100), score=iter(["<score>70</score>"] * 100))
    s0.run_all(full, "fake", ENTITIES, list(ENTITIES), measures, resume=True, **kw)
    raw = pd.read_csv(tmp_path / "raw.csv", keep_default_na=False, dtype=str)
    # 6 pairs x 2 reps + 4 entities x 2 donation + 10 credibility items x 2 samples
    assert len(raw) == 12 + 8 + 20
    assert 0 < partial < len(raw) and len(full.calls) == len(raw) - partial
    assert not raw.duplicated(["measure", "item", "entities", "rep", "sample"]).any()
    assert set(raw.loc[raw["measure"] == "credibility", "system_date"]) == {"2026-10-25"}
    with pytest.raises(ValueError, match="mix credibility dates"):
        s0.run_all(full, "fake", ENTITIES, list(ENTITIES), measures, resume=True, **{**kw, "date": "2026-10-26"})


def test_always_refusing_provider_is_missing_after_exactly_30_attempts():
    class Refuser:
        def __init__(self):
            self.n = 0

        def complete(self, messages, seed):
            self.n += 1
            return "I can't choose between these."

    chat = Refuser()
    r = s0.run_pairwise_call(chat, "Alpha Lab", "Bravo Lab", "lab", "instructed", seed=0)
    assert s0.MAX_REFUSALS == 30
    assert chat.n == 30 and r["attempts"] == 30 and r["status"] == "missing" and len(r["invalid"]) == 30
    chat = Refuser()
    assert s0.run_pairwise_call(chat, "Alpha Lab", "Bravo Lab", "lab", "instructed", seed=0, max_refusals=5)["attempts"] == 5
    assert chat.n == 5


def test_run_config_records_commit_and_cap(tmp_path):
    import json
    import subprocess
    run(FakeChat(), tmp_path, ["elo"], reps=1, allow_odd_reps=True, max_refusals=7)
    cfg = json.loads((tmp_path / "run_config.json").read_text())
    head = subprocess.run(["git", "-C", str(s0.ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert cfg["max_refusals"] == 7 and cfg["model"] == "fake" and cfg["invocations"][0]["commit"] == head
    # resuming with a different cap is refused; the same cap appends an invocation
    with pytest.raises(ValueError, match="max_refusals"):
        s0.run_all(FakeChat(), "fake", ENTITIES, list(ENTITIES), ["elo"], out=tmp_path, workers=1, reps=1, allow_odd_reps=True, resume=True, max_refusals=30)
    s0.run_all(FakeChat(), "fake", ENTITIES, list(ENTITIES), ["elo"], out=tmp_path, workers=1, reps=1, allow_odd_reps=True, resume=True, max_refusals=7)
    assert len(json.loads((tmp_path / "run_config.json").read_text())["invocations"]) == 2


def test_resume_refuses_a_raw_csv_with_other_columns(tmp_path):
    (tmp_path / "raw.csv").write_text("model,measure,entities\nfake,elo,Alpha Lab|Bravo Lab\n")
    with pytest.raises(ValueError, match="not appending"):
        s0.RawWriter(tmp_path / "raw.csv", append=True)
