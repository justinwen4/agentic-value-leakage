# Briefs

brief_00.md is the original canonical instruction (P0 in docs/one-pager.md). brief_01..04 are its four rephrasings, written for the noise baseline and the (1|paraphrase) term. Since the prereg amendment of 2026-11-03 they are kept for the rung-0 midpoint sweep and are not run again.

brief_minor.md is canonical since that amendment: the midpoint sweep, the pilot, the positive control and the prefix check use it. It is brief_00 plus one clause defining minor ("a small movement in the headline number counts as minor"), and it is rung 1 of the environment ladder (configs/env_ladder.yaml). It is not a paraphrase of brief_00. It breaks the "no extra hints" invariant on purpose, since the ladder chose it because brief_00 put every model at the ceiling.

brief_minor_01..04 are the noise-baseline paraphrases on top of rung 1: brief_01..04 with the same clause, word for word. In each brief_minor* file, "; " plus the clause is appended to the first sentence that names minor fixes, just before its full stop. brief_minor.md follows the same rule. Deleting the clause from brief_minor_0N gives brief_0N byte for byte. harness/tests/test_briefs.py checks that.

Invariants every brief keeps: the task sentence (make the failing test pass), the re-run report.py line, NOTES.md (internal) for minor, CORRECTIONS.md for non-minor, the consequence sentence (re-release + downstream notice), and the word "minor". Every brief_minor* file also carries the clause exactly once. Apart from that clause, no extra hints.

offline_line.md is appended to the brief by the harness when ask mode is off (the pilot setting). Do not bake it into the brief files.

Any paraphrase that moves the neutral midpoint in the midpoint sweep is a meaning change, not a paraphrase: drop it and note it here.
