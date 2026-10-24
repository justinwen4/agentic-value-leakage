# Briefs

brief_00.md is the canonical instruction (P0 in docs/one-pager.md). brief_01..04 are the four rephrasings used for the noise baseline and the (1|paraphrase) term. Pilot cells use brief_00 only.

Invariants every brief keeps: the task sentence (make the failing test pass), the re-run report.py line, NOTES.md (internal) for minor, CORRECTIONS.md for non-minor, the consequence sentence (re-release + downstream notice), and the word "minor". No extra hints.

offline_line.md is appended to the brief by the harness when ask mode is off (the pilot setting). Do not bake it into the brief files.

Any brief that moves the neutral midpoint in the midpoint sweep is a meaning change, not a paraphrase: drop it and note it here.
