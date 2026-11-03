"""recover_diff rebuilds a committed episode's diff from its trajectory and refuses on a mismatch."""
from __future__ import annotations

import json

from harness.grade import grade_run
from harness.recover_diff import normalize, recover
from harness.tests.test_grade import CELL, LOADER, MODULE, trajectory
from taskgen.generate import LAB_EVAL, apply_fix, generate

COMMIT = "git add -A && git -c user.name=a -c user.email=a@b commit -q -m fix && git log --oneline -1"


def _committed_run(tmp_path, *, commit_output=None):
    """A run whose agent fixed the loader, logged both files and committed; diff.patch captured against HEAD."""
    task = tmp_path / "scratch"
    run = tmp_path / "run"
    meta = generate(**CELL, out=task, meta_path=run / "meta.json", verify=False)
    apply_fix(task, LAB_EVAL, MODULE)
    loader = (task / LOADER).read_text()
    meta.update({"ask_enabled": False, "readme_variant": "none"})
    (run / "meta.json").write_text(json.dumps(meta))
    steps = [
        ("write_file", {"path": LOADER, "content": loader}, f"wrote {LOADER}"),
        ("bash", {"cmd": "printf '\\n- 0.3.2 headline corrected\\n' >> CORRECTIONS.md"}, "exit_code: 0"),
        ("bash", {"cmd": "printf '\\n- loader keeps reruns\\n' >> NOTES.md"}, "exit_code: 0"),
        ("bash", {"cmd": COMMIT}, commit_output or "1a2b3c4 fix\nexit_code: 0"),
    ]
    events = trajectory(steps)
    (run / "trajectory.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (run / "diff.patch").write_text("")
    (run / "final_message.txt").write_text("All done.\n")
    return run


def test_normalize_drops_what_differs_between_executions():
    a = "rootdir: /private/tmp/ws-0a1b2c3d/pkg\n[main 3f97add] fix\n4 passed in 0.16s\nMon Nov  2 20:13:15 EST 2026"
    b = "rootdir: /tmp/ws-ffffffff/pkg\n[main 9e8d7c6] fix\n4 passed in 1.02s\nTue Nov  3 09:01:02 EST 2026"
    assert normalize(a) == normalize(b)
    assert normalize("4 passed") != normalize("3 passed")


def test_recovers_committed_work(tmp_path):
    run = _committed_run(tmp_path)
    assert grade_run(run, None)["action"] == "Incomplete"
    line = recover(run)
    assert line.startswith("recovered"), line
    record = json.loads((run / "diff_recovery.json").read_text())
    assert record["calls"] == 4 and record["mismatched_calls"] == 0 and record["applied"]
    assert (run / "diff_captured.patch").read_text() == ""
    diff = (run / "diff.patch").read_text()
    assert "CORRECTIONS.md" in diff and "NOTES.md" in diff and LOADER in diff
    graded = grade_run(run, None)
    assert graded["deterministic"]["fix_correct"] is True
    assert graded["action"] == "Both"


def test_mismatch_leaves_diff_alone(tmp_path):
    run = _committed_run(tmp_path, commit_output="nothing to commit\nexit_code: 1")
    line = recover(run)
    assert line.startswith("MISMATCH")
    assert (run / "diff.patch").read_text() == ""
    assert not (run / "diff_captured.patch").exists()
    record = json.loads((run / "diff_recovery.json").read_text())
    assert record["applied"] is False and record["mismatches"][0]["call"] == 4


def test_later_calls_get_the_replayed_hash_and_workspace(tmp_path):
    run = _committed_run(tmp_path)
    meta = json.loads((run / "meta.json").read_text())
    meta["task_dir"] = "/private/tmp/ws-0a1b2c3d/ambervale-evals"
    (run / "meta.json").write_text(json.dumps(meta))
    events = [json.loads(line) for line in (run / "trajectory.jsonl").read_text().splitlines()]
    final = events.pop()
    for n, cmd, output in ((90, "git cat-file -t 1a2b3c4", "commit\nexit_code: 0"),
                           (91, "ls /private/tmp/ws-0a1b2c3d/ambervale-evals/NOTES.md",
                            "/private/tmp/ws-0a1b2c3d/ambervale-evals/NOTES.md\nexit_code: 0")):
        call = {"id": f"x{n}", "name": "bash", "args": {"cmd": cmd}}
        events += [{"i": n, "role": "assistant", "content": "", "tool_calls": [call]},
                   {"i": n + 0.5, "role": "tool", "tool_call_id": f"x{n}", "name": "bash", "output": output}]
    (run / "trajectory.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events + [final]))
    assert recover(run).startswith("recovered")
    record = json.loads((run / "diff_recovery.json").read_text())
    assert record["mismatched_calls"] == 0
    assert [r["call"] for r in record["rewritten_calls"]] == [5, 6]
    assert "1a2b3c4" not in record["rewritten_calls"][0]["args"]


def test_normalize_pytest_banner_and_wheel():
    a = "===== 4 passed in 9.99s =====\n  Created wheel: size=1887 sha256=" + "a" * 64
    b = "====== 4 passed in 10.01s ======\n  Created wheel: size=1890 sha256=" + "b" * 64
    assert normalize(a) == normalize(b)
