# 06 — Reflection and Persistent Memory

## Non-negotiable distinction
The model is hosted and called through OpenRouter. Do not train, fine-tune, or modify weights. Improvement comes from evidence-backed memory, prompt/context changes, and validated system logic.

## Loop
1. Save the original prediction and its exact context/configuration.
2. Wait until its outcome resolves (next opposite signal).
3. The deterministic evaluator produces the outcome record and flags a **mistake** per the evaluator's versioned definition.
4. Mistakes are sent to the model for reflection: what might have gone wrong. The system also supplies a few resolved *correct* signals under the same conditions as contrast evidence, so lessons are not built from failures alone.
5. The reflection is stored as a `CANDIDATE` lesson.
6. The model judges its own confidence in the lesson (see Validation). Validated lessons become retrievable.
7. Future inference receives only validated lessons whose conditions match.
8. Memory and prompt changes are versioned for comparison and rollback.

## Reflection output (structured, schema-validated)
`observed_fact` (no interpretation), `hypothesis` (marked unvalidated), `candidate_lesson` (narrow, testable), `conditions` (what situation it applies to: free text/tags written by the model), `cited_signal_ids` (cases the model believes support it), `model_confidence`, `uncertainty_and_counterexamples`, and an explicit abstain option when evidence is insufficient. The system fills `instrument`, the **timeframe set**, the **context version** and the **model** in scope automatically.

## Validation: model-judged, system-verified
No engineered promotion thresholds. The model decides; the system supplies the facts.
1. The system looks up every cited signal ID: it must exist, be resolved, and match scope. Invalid or unresolved IDs are dropped and logged.
2. The system computes the **real counts** (times right / times wrong) over the verified cases. The model never supplies these counts from its own recall.
3. Cases that share an exit window (overlapping same-direction signals) are marked as such, since they are not independent evidence.
4. A first call asks the model to select, from the cases that resolved after the lesson was created, those that match its conditions; the system verifies the ids and computes the counts. A second call gives the model the lesson, the verified counts, and the evidence. Evidence must include cases that **resolved after the candidate was created**; the originating cases are shown separately and not counted as independent validation.
5. The model returns `model_confidence` and a `verdict`: `PROMOTE`, `KEEP_CANDIDATE`, `REJECT`, or `RETIRE`, with reasoning. The system applies it.
6. Re-judgment happens when new resolved cases in the lesson's scope exist, at a configurable cadence. A validated lesson that later fails can be `RETIRED` by the same process.
A `PROMOTE` verdict is applied only when at least one verified post-creation case supports it; evidence-free promotion is never granted.
Statuses: `CANDIDATE`, `VALIDATED`, `REJECTED`, `RETIRED`. Log every verdict. Model confidence is the model's judgment, not a calibrated probability; the shadow comparison in 05 is the real test of whether memory helps.

## Retrieval (matching conditions)
- Hard filter: same instrument, **same timeframe set**, **same context version**, **same model**, status `VALIDATED`, validated before the prediction time.
- The model sees the conditions of each lesson and decides applicability.
- Cap the number of lessons per call (config `K`); order by model confidence, then recency.
- Record lesson IDs and memory version on each prediction. Never send the entire memory store.
- Changing the timeframe set, the context version or the model means starting with no lessons for it; lessons from another set are not mixed in.
- Retrieval must be switchable off for shadow runs.

## Memory hygiene
One mistake creates a candidate, never a universal rule. Avoid redundant or contradictory lessons. Never overwrite historical predictions or evaluations.

## Failure handling
If reflection or validation calls fail, preserve the signal and outcome; the work is retryable and never blocks signal delivery. Missing memory is preferable to unvalidated or fabricated lessons.
