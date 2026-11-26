# Expert checks for the EvidenceBook report

These two checks are for an operator, not taught to an agent: the
[evidencebook-report skill](../SKILL.md) teaches only the five verbs (check, record, ask,
verify, show). Their instructions are kept here as they were taught before.

## Resolve a judge pin by hand

`capsulectl judge pin FILE` resolves the pinned judge (model id, prompt digest, axes digest,
sampling). For a judged pack, the pack's judge pin must resolve before a grade 2 report is
built, as [`daily-judge-and-close`](../../daily-judge-and-close/SKILL.md) requires; its judge
run resolves it in step 1. Run on its own, the check is an action, so seal it with
`scripts/skill_action.py` as a `skill-action/v1` capsule, digests only, as the skill's
"Every action seals a record" section says.

## Show what a stranger sees

"Show me what they see" asks the holder's own responder as a stranger would:
`capsulectl book doctor --probe`. It asks for checkpoints, then `history_card/1` (which Steven's ruling u632 retired as an
asked form; moving the probe to `history_card/2` is tracked in action-state-group/evidencebook#995), through the
in-process `book respond` path (no `--requester`, not a network endpoint), verifies both and
shows the answer. A match shows what a stranger is served, not that the share policy is
verified. It seals nothing.
