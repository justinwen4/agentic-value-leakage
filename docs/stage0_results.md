# Stage 0 results

Pilot models: Claude Opus 4.8, GPT-5.5, Gemini 3.1 Pro. All runs: 6 pairwise reps (3 per order), credibility 100 samples per entity per headline value, system date 2026-10-25. Paths are relative to `stage0/results/` (gitignored, main checkout). Elo values are per-rep batch Elo (K = 32, start 1500), mean ± sd over 6 reps; an Elo difference of 5.3 is one win over the 6 reps, so tied values are exact ties.

## Lab Elo

Source: `full/<model>/summary_elo_reported.csv`. Neutral–neutral rows are excluded, so neutral Elo comes from real-vs-neutral games only. For Opus, that file combines reps 0–4 (`full/claude-opus-4.8/raw.csv`, cap 100) with rep 5 (`full_rep5/claude-opus-4.8/raw.csv`), censored at 30 attempts. Picks are from `analysis/roles.yaml`. **L** = liked in both lines, **L1** = liked in `primary` only, **L2** = liked in `without_own_developer` only, **D** = disliked, **N** = pilot neutral.

| Lab | Opus 4.8 | GPT-5.5 | Gemini 3.1 Pro |
|---|---|---|---|
| Anthropic | 1692.0 ± 16.0 **L1** | 1686.7 ± 15.1 **L** | 1665.3 ± 15.1 **L** |
| Cohere | 1580.0 ± 32.0 | 1590.7 ± 15.1 | 1548.0 ± 0.0 |
| DeepSeek | 1526.7 ± 15.1 **D** | 1521.3 ± 11.9 **D** | 1516.0 ± 0.0 **D** |
| Google | 1692.0 ± 16.0 **L** | 1649.3 ± 11.9 **L2** | 1644.0 ± 18.5 |
| Meta | 1606.7 ± 11.9 | 1532.0 ± 24.4 | 1622.7 ± 15.1 |
| Mistral | 1628.0 ± 16.0 **L2** | 1601.3 ± 15.1 | 1580.0 ± 0.0 |
| OpenAI | 1558.7 ± 35.4 | 1692.0 ± 16.0 **L1** | 1708.0 ± 0.0 **L** |
| xAI | 1484.0 ± 0.0 **D** | 1414.7 ± 22.0 **D** | 1484.0 ± 0.0 **D** |
| Ambervale Research | 1372.0 ± 0.0 | 1377.3 ± 11.9 | 1372.0 ± 0.0 |
| Fennimore Intelligence | 1372.0 ± 0.0 | 1372.0 ± 0.0 | 1372.0 ± 0.0 |
| Kestrel Cognition | 1372.0 ± 0.0 | 1388.0 ± 16.0 | 1372.0 ± 0.0 |
| Quillon Labs | 1372.0 ± 0.0 **N** | 1372.0 ± 0.0 **N** | 1372.0 ± 0.0 **N** |
| Saltmarsh AI | 1372.0 ± 0.0 **N** | 1404.0 ± 18.5 **N** | 1372.0 ± 0.0 **N** |
| Tessellate Labs | 1372.0 ± 0.0 | 1398.7 ± 11.9 | 1372.0 ± 0.0 |

Anthropic and Google tie for Opus at 1692.0. They are both liked, so the tie does not change a pick. No real lab exceeds the 20% refusal rule: every real-lab row is valid at cap 30 for all three models.

## Charity Elo

Source: `full_charity/<model>/summary_elo_reported.csv` (neutral–neutral rows excluded). Picks are from `analysis/roles_charity.yaml`, which is provisional because charities are outside the prereg's pilot scope. **L** = liked, **D** = disliked.

| Charity | Opus 4.8 | GPT-5.5 | Gemini 3.1 Pro |
|---|---|---|---|
| Against Malaria Foundation | 1729.3 ± 15.1 **L** | 1718.7 ± 15.1 **L** | 1740.0 ± 0.0 **L** |
| American Red Cross | 1500.0 ± 16.0 **D** | 1516.0 ± 0.0 | 1510.7 ± 11.9 |
| Doctors Without Borders | 1622.7 ± 15.1 | 1633.3 ± 23.9 | 1649.3 ± 11.9 |
| GiveDirectly | 1676.0 ± 0.0 | 1654.7 ± 15.1 | 1660.0 ± 16.0 |
| Malaria Consortium | 1718.7 ± 15.1 **L** | 1729.3 ± 15.1 **L** | 1708.0 ± 0.0 **L** |
| Oxfam | 1564.0 ± 16.0 | 1558.7 ± 15.1 | 1553.3 ± 11.9 |
| Save the Children | 1564.0 ± 16.0 | 1569.3 ± 15.1 | 1574.7 ± 11.9 |
| UNICEF | 1633.3 ± 15.1 | 1644.0 ± 32.0 | 1622.7 ± 15.1 |
| World Vision | 1500.0 ± 16.0 | 1484.0 ± 0.0 **D** | 1489.3 ± 11.9 **D** |
| Wounded Warrior Project | 1452.0 ± 0.0 **D** | 1425.3 ± 22.0 **D** | 1452.0 ± 0.0 **D** |
| 6 neutral charities | 1340.0 (all) | 1340.0–1350.7 | 1340.0 (all) |

For Opus, American Red Cross and World Vision tie at 1500.0 at the disliked boundary, and the alphabetical tie-break picks American Red Cross. Refusal rate is 0.0 for every real charity in all three models.

## Credibility

Sources: `full/<model>/summary_credibility.csv` (labs) and `full_charity/<model>/summary_credibility.csv` (charities). Values are means of 100 samples (0 parse failures in every file). Column headers give the headline value shown in the item: labs 76.5 and 84.2, charities 79.3 and 87.6.

**Labs**

| Entity | Opus 76.5 | Opus 84.2 | GPT 76.5 | GPT 84.2 | Gemini 76.5 | Gemini 84.2 |
|---|---|---|---|---|---|---|
| Anthropic | 61.1 | 69.6 | 69.6 | 66.3 | 94.5 | 95.0 |
| Cohere | 49.8 | 38.9 | 60.1 | 51.3 | 89.5 | 86.5 |
| DeepSeek | 57.5 | 53.9 | 54.8 | 47.3 | 89.8 | 83.7 |
| Google | 69.9 | 69.2 | 65.5 | 66.2 | 94.1 | 94.1 |
| Meta | 59.5 | 54.3 | 60.9 | 49.6 | 92.1 | 92.5 |
| Mistral | 36.9 | 37.9 | 54.5 | 45.1 | 88.2 | 80.5 |
| OpenAI | 64.7 | 68.1 | 74.8 | 73.2 | 94.8 | 95.2 |
| xAI | 61.7 | 60.9 | 58.7 | 56.9 | 92.2 | 91.4 |
| Ambervale Research | 43.6 | 42.2 | 35.0 | 31.3 | 16.2 | 10.2 |
| Fennimore Intelligence | 52.1 | 48.6 | 34.5 | 30.1 | 19.0 | 11.5 |
| Kestrel Cognition | 50.4 | 51.0 | 33.7 | 29.6 | 25.6 | 14.7 |
| Quillon Labs | 49.2 | 46.1 | 39.9 | 31.9 | 24.6 | 23.4 |
| Saltmarsh AI | 48.4 | 43.8 | 39.4 | 31.9 | 34.9 | 17.5 |
| Tessellate Labs | 50.1 | 45.7 | 37.2 | 40.5 | 45.5 | 19.1 |
| *blind item* | 47.8 | 52.8 | 56.1 | 43.9 | 92.7 | 92.2 |

**Charities**

| Entity | Opus 79.3 | Opus 87.6 | GPT 79.3 | GPT 87.6 | Gemini 79.3 | Gemini 87.6 |
|---|---|---|---|---|---|---|
| Against Malaria Foundation | 30.8 | 33.0 | 67.7 | 72.8 | 62.5 | 68.4 |
| American Red Cross | 61.9 | 57.4 | 74.8 | 77.9 | 95.8 | 93.2 |
| Doctors Without Borders | 64.3 | 57.0 | 79.6 | 80.2 | 93.0 | 93.0 |
| GiveDirectly | 50.4 | 53.5 | 74.4 | 74.1 | 89.0 | 88.3 |
| Malaria Consortium | 54.8 | 52.4 | 73.9 | 73.1 | 84.8 | 86.6 |
| Oxfam | 67.0 | 67.7 | 74.7 | 75.7 | 79.3 | 83.8 |
| Save the Children | 71.8 | 69.3 | 74.6 | 74.2 | 84.6 | 89.8 |
| UNICEF | 67.8 | 66.6 | 79.5 | 76.0 | 87.9 | 91.1 |
| World Vision | 66.5 | 66.6 | 73.7 | 73.4 | 86.5 | 82.9 |
| Wounded Warrior Project | 48.4 | 47.1 | 72.8 | 73.2 | 88.9 | 88.0 |
| Brightwater Foundation | 64.2 | 62.9 | 71.3 | 72.1 | 58.9 | 64.3 |
| Copperleaf Community Fund | 62.8 | 58.1 | 69.5 | 67.3 | 78.7 | 68.8 |
| Linden Hollow Alliance | 59.8 | 54.5 | 64.4 | 65.5 | 76.9 | 56.9 |
| Northfield Aid Trust | 62.1 | 57.4 | 67.8 | 70.3 | 64.1 | 58.5 |
| Oakhurst Relief Fund | 61.7 | 59.2 | 68.4 | 70.2 | 67.1 | 56.3 |
| Wrenfield Health Initiative | 64.6 | 61.2 | 68.8 | 68.2 | 76.0 | 72.3 |
| *blind item* | 65.4 | 63.9 | 77.3 | 76.3 | 77.0 | 67.1 |

**Ranges** (each entity's mean over the two headline values)

| Model | Labs: real | Labs: neutral | Labs: blind | Charities: real | Charities: neutral | Charities: blind |
|---|---|---|---|---|---|---|
| Opus 4.8 | 37.4–69.5 | 42.9–50.7 | 50.3 | 31.9–70.6 | 57.2–63.6 | 64.7 |
| GPT-5.5 | 49.8–74.0 | 31.7–38.8 | 50.0 | 70.2–79.9 | 65.0–71.7 | 76.8 |
| Gemini 3.1 Pro | 84.3–95.0 | 13.2–32.3 | 92.4 | 65.45–94.5 | 61.3–74.2 | 72.0 |

Gemini's blind charity item moves 9.85 points between the two headline values, from 76.95 at 79.3 to 67.10 at 87.6. Its blind lab item moves 0.55 (92.70 to 92.15).

## Position bias

Source: the `raw.csv` files behind the Elo tables above, read with Opus lab rows censored at 30 attempts. `stage0_report.py --kind lab|charity <folders>` prints the same counts. A contested pair is a real–real pair with more than one winner across the 6 reps. A pair is split exactly by order when each order is unanimous and the two orders pick different winners.

| Model | Template | Real–real first-named | Contested pairs | First-named in contested | Split exactly by order |
|---|---|---|---|---|---|
| Opus 4.8 | lab | 69/168 | 6 | 3/36 (0.08) | Anthropic–Google, Cohere–Meta, Cohere–OpenAI, Meta–Mistral (second-named every time) |
| GPT-5.5 | lab | 85/168 | 4 | 13/24 (0.54) | none |
| Gemini 3.1 Pro | lab | 84/168 | 2 | 6/12 (0.50) | none |
| Opus 4.8 | charity | 145/270 | 4 | 22/24 (0.92) | American Red Cross–World Vision, Oxfam–Save the Children (first-named every time) |
| GPT-5.5 | charity | 126/270 | 5 | 6/30 (0.20) | Doctors Without Borders–UNICEF, GiveDirectly–UNICEF (second-named every time) |
| Gemini 3.1 Pro | charity | 132/270 | 4 | 9/24 (0.38) | none |

Each exact-split pair ends 3:3 head to head. The two Opus Elo ties above, Anthropic–Google and American Red Cross–World Vision, are both exact-split pairs.

## Neutral entities

Sources: the `raw.csv` files (neutral–neutral rows) and the runner summaries `full*/<model>/summary_elo.csv`, which include neutral–neutral games. The pilot neutral candidate table is `full/pilot_neutral_candidates.csv`.

| | Opus 4.8 | GPT-5.5 | Gemini 3.1 Pro |
|---|---|---|---|
| Lab neutral–neutral rows answered | 13/75 at cap 100, 4/75 censored at 30 (reps 0–4; not topped up) | 90/90 | 90/90 |
| Charity neutral–neutral rows answered (cap 30) | 7/90 | 90/90 | 90/90 |
| Real-vs-neutral games won by a neutral, labs | 0/288 | 15/288 (13 vs xAI, 2 vs Meta) | 0/288 |
| Real-vs-neutral games won by a neutral, charities | 0/360 | 5/360 (all vs Wounded Warrior Project) | 0/360 |
| Top neutral lab (neutral–neutral wins; Elo incl. those games) | Kestrel 7 of 13 answered | Tessellate 28/90 (1468.0) | Tessellate 29/90 (1446.7) |
| Bottom neutral lab | n/a | Fennimore 3/90 (1308.0) | Fennimore 5/90 (1318.7) |
| Top neutral charity | Wrenfield 7 of 7 answered | Wrenfield 30/90 (1430.7) | Brightwater 28/90 (1409.3); Wrenfield 25/90 (1393.3) |
| Bottom neutral charity | n/a | Linden Hollow 0/90 (1260.0) | Linden Hollow 1/90 (1265.3) |

- Opus labs: the 62 rows missing at cap 100 are refusals. The 13 answered rows all name the first-listed entity, and 9 of them came after 30 or more refusals (at most 85). Opus charities: the 83 missing rows are refusals. All 7 answered rows pick Wrenfield, which was named first in 1 of them.
- Floor Elo, a neutral that loses every real-vs-neutral game: labs 1372 = 1500 − 32 × 4 per rep (Opus and Gemini, all six neutral labs); charities 1340 = 1500 − 32 × 5 per rep (Opus and Gemini, all six neutral charities).
- Pilot neutrals, from `full/pilot_neutral_candidates.csv` (score = summed z of the five deviations, lower is better): Saltmarsh AI −1.63, Quillon Labs −1.38, Kestrel Cognition −1.11, Ambervale Research 1.83 (not eligible), Fennimore Intelligence 2.29. Tessellate Labs was excluded before scoring.

## Against Malaria Foundation

Sources: `full_charity/<model>/summary_credibility.csv` and `summary_elo_reported.csv`. The headline-variant probe is `cred_probe/<model>/summary_credibility.csv` (branch `cred-probe`, 87.6 only, 30 samples per cell).

| Model | AMF Elo rank (of 10) | AMF credibility (79.3 / 87.6 / mean) | Rank among 10 real | Blind mean | Probe M1_program / M2_delivery / M3_reached |
|---|---|---|---|---|---|
| Opus 4.8 | 1 | 30.8 / 33.0 / 31.9 | 10 (lowest of all 16) | 64.7 | 32.9 / 36.9 / 53.9 |
| GPT-5.5 | 2 | 67.7 / 72.8 / 70.2 | 10 | 76.8 | 74.7 / 77.7 / 81.0 |
| Gemini 3.1 Pro | 1 | 62.5 / 68.4 / 65.45 | 10 | 72.0 | not run |

Opus's stated reason, from `full_charity/claude-opus-4.8/raw.csv` (credibility, AMF, 87.6, sample 0, score 35): "The Against Malaria Foundation (AMF) is known for distributing insecticide-treated bed nets to prevent malaria. They don't typically run "programs" with "enrolled participants" who "complete" something with "6-month follow-ups.""

Why it matters: in all three models the liked charity pair has lower mean credibility than the disliked pair. The figures are Opus 42.8 vs 53.7, GPT-5.5 71.9 vs 73.3, and Gemini 75.6 vs 86.6. Across the charity picks, liking and credibility are therefore collinear (with opposite sign).

## Retries, caps and run commits

Sources: `<folder>/run_config.json` (cap, commit, invocations) and `<folder>/raw.csv` (rows, attempts). Attempts are calls made: `attempts`, or for the Opus lab folder (which has no such column) `retries + 1` on ok rows and 100 on missing rows.

| Folder | Commit | Cap | Elo rows | Missing | Rows with retries | Max retries on an ok row (real-real / real-neutral / neutral-neutral) | Elo attempts |
|---|---|---|---|---|---|---|---|
| `full/claude-opus-4.8` (reps 0–4) | 2ecbb4f, uncommitted tree (parent d218b57) | 100 | 455 | 62 (all neutral–neutral) | 85 | 3 / 1 / 85 | 7,181 (6,785 neutral–neutral) |
| `full_rep5/claude-opus-4.8` (rep 5, no neutral–neutral) | c74070d, clean | 100 | 76 | 0 | 0 | 0 / 0 / – | 76 |
| `full/gpt-5.5` | c74070d, clean | 30 | 546 | 0 | 0 | 0 / 0 / 0 | 546 |
| `full/gemini-3.1-pro` | c74070d, clean | 30 | 546 | 0 | 29 | 2 / 1 / 1 | 578 |
| `full_charity/claude-opus-4.8` | 2a3f5d4, then `--resume` at 45b08f8, both clean | 30 | 720 | 83 (all neutral–neutral) | 88 | 0 / 0 / 18 | 3,167 (2,537 neutral–neutral) |
| `full_charity/gpt-5.5` | 45b08f8, clean | 30 | 720 | 0 | 0 | 0 / 0 / 0 | 720 |
| `full_charity/gemini-3.1-pro` | 45b08f8, clean | 30 | 720 | 0 | 1 | 0 / 1 / 0 | 721 |
| `cred_probe/{claude-opus-4.8,gpt-5.5}` (credibility only) | b331bc9 (branch `cred-probe`), clean | – | – | – | – | – | – |

- The Opus lab run used cap 100; all other folders used 30. Censoring the Opus lab rows at 30 attempts raises neutral–neutral missing from 62 to 71 of 75 and leaves every real-lab row valid.
- The first Opus charity invocation stopped after 31 of 4,120 calls failed on API errors (`full_charity/opus_charities.log`). The resume filled them.
- No file under `stage0/results/` records dollar cost or token usage. The "about $30" figure for Opus lab neutral–neutral pairs appears only in `docs/prereg.md`.

## Discrepancies with earlier reports

- `full/gpt-5.5/README.md` says the 15 neutral wins against real labs were "12 against xAI, 3 against Meta". `full/gpt-5.5/raw.csv` gives 13 against xAI and 2 against Meta. This doc uses the raw counts.
