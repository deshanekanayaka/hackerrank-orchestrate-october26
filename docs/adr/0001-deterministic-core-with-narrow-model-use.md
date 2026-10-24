# Deterministic core, with the model used only where code is weak

The grader compares `resource_id`, `operation`, `state`, `evidence_id`, and
step order exactly, and the 32 sample answers show a mechanical structure. So
ordinary Python owns identity resolution, evidence indexing, state decisions,
policy application, step ordering, and serialization. A model is called in
only two places: intent classification for the 518 request texts, and a
one-time transcription of the 11 screenshots and 4 PDF documents.

We rejected a model-per-case agent, because a model drifts on exact
identifiers and on array order, which is most of the score. We rejected a
zero-model solution, because the challenge asks for an AI-powered agent and
the submission must report model calls, tokens, and cost.

## Consequences

The model never decides a case status and never writes a step field. Model
output is cached on disk and committed, so a clean checkout can rebuild
`output.csv` with no API key.
