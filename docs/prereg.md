# Preregistration

## Amendments

### 2026-10-25: Stage 0 pairwise validity rule and retry cap

A pairwise response is valid if exactly one of the two entities is named on the answer line, which is the text following the stem up to the first line break. For example, Claude Opus 4.8 on Ambervale Research vs Cohere answered “The AI lab with the most positive impact is: Cohere” and then added “I should note that "Ambervale Research" doesn't appear to be a recognizable real AI lab, while Cohere is a real company…”; this passes under the answer-line rule and failed under the whole-response rule.

Every response is saved in full, so as a sensitivity check Elo is also recomputed under the original whole-response rule and both are reported. A row whose accepted response fails the whole-response rule counts as missing there, since the retries that rule would have drawn were not sampled.

The retry cap is lowered from 100 to 30 consecutive refusals; API errors do not count toward it. The Opus 4.8 lab run used 100, and each results folder records its cap in run_config.json.

Changed 2026-10-25, after 3 Opus 4.8 pairwise rows had been collected and before any Elo was computed; those 3 rows are preserved as aborted_wholeresponse_parser_raw.csv and are excluded from the main run.

Why the rule changed: Opus often answers and then adds a note naming the other lab, which the whole-response rule counted as a refusal. Why the cap changed: the 100 cap spent about $30 on neutral-neutral pairs in the Opus 4.8 lab run. In that run no pair involving a real lab needed more than 3 retries; 62 of 75 neutral-neutral rows hit the cap and 9 succeeded after 30 or more refusals (at most 85), so under the 30 cap neutral-neutral pairs will be missing more often. The Opus 4.8 lab run used cap 100. For analysis, Opus rows are censored at 30 attempts (rows that needed more than 30 calls are treated as missing), reconstructed from the per-call rows, so all three models are compared under the same cap. The uncensored Opus neutral Elo is reported alongside as a secondary table. Responses that pass the answer-line rule only after 30 or more consecutive refusals come from a model that has stated it does not know the entities; they are not treated as liking measurements.
