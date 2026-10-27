# AI-use declaration

Name: Zhang Bowen (张博文). Student ID: 12410604. Identity is included in the local deliverables.

## Tools used

Two large language models were used, in separate sessions of Claude Code with
the provider switched between sessions using CC Switch (cc-switch):

| Session | Provider | Displayed version | Dates | Browsing | Code execution |
|---|---|---|---|---|---|
| Model A | Kimi | not disclosed by the interface | 2026-10-10 | no | yes (local Python) |
| Model B | DeepSeek | not disclosed by the interface | 2026-10-11 | no | yes (local Python) |
| Report drafting and independent verification | OpenAI / Codex desktop | interface version not confirmed | 2026-10-10 to 2026-10-11 | yes | yes (local Python) |

Software: Python 3 (Anaconda), NumPy 2.4.6, SciPy 1.16.3; master seed 20260927.
The supplied records describe the Kimi and DeepSeek sessions as using redacted excerpts. The local report identity and assignment files were provided in the Codex session. No broader assertion that no identifying information was ever supplied to any AI is made.

## Assistance by problem

**Part III (I1-I3)** -- the primary documented use:
- I1: the supplied records contain both models' classifications. I1(b) was subsequently re-derived after correcting the recorded formula. Original and independent revised numerical evidence are distinguished in the report.
- I2: the supplied records contain diagnoses, complete code exchanges and proposed patches; the suites were independently rerun and extended in the Codex session.
- I3: the supplied records contain generated questions, formatted attempts, feedback and reflection. Their mathematical answers were independently checked; the student confirmed on October 11 that the attempts preceded feedback and the reflection represents their actual experience.

**Part I (Theory), T1–T15:** OpenAI/Codex helped draft mathematical reasoning, proofs, no-arbitrage cash-flow arguments, numerical replication checks and the English report. These sections are not represented as unaided student work.

**Part II (Algorithms), A1–A5:** OpenAI/Codex drafted the Python implementations, experiment driver and extended tests; executed the simulations and tests; generated the assessed figures and result tables; and helped interpret uncertainty. The original course scaffold, starter tests, parameters and intentionally flawed debugging file were reused. The student's prior independent contribution, if any, must be separately described from genuine records; none is invented here.

## Independent contribution and verification

- Mathematical claims and computational outputs were checked through derivations, actual numerical reruns, draw reconstruction, model identities and boundary tests. Codex performed the independent verification documented in this package. The student must review and be able to explain the submitted material; that understanding is not certified on the student's behalf.
- For Part III the supplied records include pre-diagnosis material, checks, proposed code and formatted I3 attempts. The final report distinguishes these records from independently run checks and identifies the subsequent I1(b) revision. On October 11 the student explicitly confirmed I3's actual attempt-before-feedback chronology and the factual basis of the personal reflection.
- The proposed model patches are preserved separately from the final independently validated repair. Residual proposed-patch defects and model explanation errors are reported rather than concealed.
- Reused materials include the supplied assignment scaffold, starter tests, parameters and debugging exercise, in addition to standard NumPy/SciPy routines. Newly drafted code and report text are AI-assisted.

## Disclosure statement

All I1-I3 transcripts in `ai_logs/` record the two real sessions; no
interaction was invented. One post-session revision is disclosed here: in the first I1
prompt the four claims were transcribed into the log with the `t` accidentally
dropped from statement (b) -- `D0(1+rc/m)^m` instead of the handout's
`D0(1+rc.t/m)^m`. After correcting the transcription, the passages for statement (b) were re-derived against the correct formula rather than retained as unchanged verbatim model replies and the numeric test
was re-run; the other three statements and all of I2-I3 are as originally
exchanged. All numerical results and test outputs are from actual runs of the
scripts in `ai_logs/` with the stated seed and versions; the illustrative
figures shipped with the assignment are not reported as my results. The assistance scope is disclosed above. The student has confirmed the I3 chronology and reflection. This disclosure preserves the actual AI assistance and does not claim unaided authorship of the AI-assisted theory or algorithms.

The supplied declaration states that the logs otherwise reflect real sessions. That statement is retained as source-provided provenance; numerical reproduction does not independently authenticate a conversation chronology. Full-code I2 records are now included. The private Chinese README is excluded from the submission archive without removing the AI-use disclosure or substantive revision history.
