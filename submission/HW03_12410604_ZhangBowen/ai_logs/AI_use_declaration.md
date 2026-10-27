# AI-use declaration and current status

Prepared on 2026-10-21 (Asia/Shanghai). This is an assisted worked-solution document, not an assertion of completed personal course requirements.

The student asked for the homework to be completed according to its requirements, then chose to receive question-by-question worked solutions before a ZIP, and subsequently requested packaging of the existing materials. The student expressly reported no prior independent draft, pre-AI debugging record or book-reading record. These absences are not reconstructed or backdated.

## Attribution correction

Earlier drafts of this package labelled the assistant and the audit sessions as OpenAI models with `gpt-6-*` routing labels. **That labelling was incorrect.** The runtime used for this package is **DeepSeek**, as confirmed by the student and reported by the session environment (`deepseek-flash`). No OpenAI model was used. The labels in the logs and report have been corrected; the conversation content is otherwise preserved. The exact backend build or revision identifier was not exposed by the interface, so no claim is made about a specific DeepSeek release.

The I1 assignment asks for two distinct LLMs. Two independently prompted DeepSeek sessions (Model A and Model B) were used, with separate contexts and separate replies. The interface did not expose distinct backend model identifiers for those two dispatches, so this package does **not** claim two different vendors or two different model families. A reader who requires two vendor-distinct models should treat this as a limitation of the recorded audit rather than as satisfied evidence.

## Actual tools and models

| Use | Provider / runtime | Date | Browsing or execution during substantive replies |
|---|---|---|---|
| Orchestration, mathematical checks, programming, report | DeepSeek / `deepseek-flash` runtime label | 2026-10-21 | browsing and local execution available and actually used |
| I1 Model A (independent audit session) | DeepSeek / separately prompted session | 2026-10-21 | no browsing or execution while answering |
| I1 Model B (independent audit session) | DeepSeek / separately prompted session | 2026-10-21 | no browsing or execution while answering |
| I2 repair model (independent session) | DeepSeek / separately prompted session | 2026-10-21 | no test execution while proposing repairs; wrote patch files; orchestrator ran checks |

The orchestrator, rather than the student personally, issued the recorded prompts.

## Assistance and verification

T1–T8 derivations and English/Chinese prose were AI-assisted. A1–A3 implementations, experiments, tests, plots and interpretations were AI-assisted. Numerical results are from actual final-count executions. I1 has two substantive initial responses and two substantive follow-ups per session. I2 preserves the supplied instructor original, a first proposal with an API regression, a repaired version, all three substantive exchanges, and actual checks (1/11, 8/11, 11/11, plus 44 demanding cases).

The original code was supplied by the user as `C:/Users/Admin/Downloads/code.zip`; it is instructor-authored intentionally flawed teaching code. The initial diagnosis saved in this session is the assistant's diagnosis before contacting the separate repair session. It is **not** the student's required pre-AI independent attempt, and the report says so explicitly.

For R1 the agent consulted Tsay's public Wiley chapter excerpt (third edition, pp. 2--23) and a complete course copy of Hull's Chapter 14 in the **ninth-edition printing**, pp. 302--320. The assignment specifies the eleventh U.S. edition. The eleventh edition was not lawfully accessible in full from this environment: the publisher catalog and the official eleventh-edition chapter structure were checked, but no complete eleventh-edition chapter text was obtained. The report therefore cites the eleventh edition's Chapter 14 section names where they are confirmed by the publisher's contents, labels every page actually read as a ninth-edition page, and does not attribute ninth-edition equation numbers to the eleventh edition. The source-based reconstructions, checked examples, and cross-book comparison are AI-assisted; the student's personal reading is not attested. Bibliographic pages and search snippets are not counted as book reading.

Full actual I1/I2 exchanges are preserved, including limitations, failed tests and follow-ups. Machine-readable exports retain visible user/assistant messages and tool calls/results up to their recorded cutoff; they exclude private reasoning, system/developer text and account/session internals. The existing materials are now packaged at the student's request; packaging and final handoff after the export cutoff are administrative.
