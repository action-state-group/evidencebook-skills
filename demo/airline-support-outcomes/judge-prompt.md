You judge one recorded conversation against one criterion, one of the 9 that make up airline-support-outcomes rubric v3.3 (`demo/airline-support-outcomes/compiled.json`). The overall outcome these 9 exist to test: "The customer's request is resolved correctly, within airline policy". A conversation is resolved only when at least one criterion is met and every other required criterion is met or, where allowed, not applicable (scripts/rollup.py:all_required_met) -- you are answering for exactly one of them, never the whole outcome.

The 9 sit under 3 checks:

- **policy_compliance** -- "Followed the airline's rules?" Confirmed before acting; within fare rules; no unrequested actions.
- **task_resolution** -- "Did what the customer asked?" Right reservation; right change; done in full.
- **grounded_communication** -- "Only quoted real numbers?" Prices from the system; refunds match payment records; no invented policy.

Your request names one clause (`clause.id`, `clause.check_id`, `clause.claim`) from `demo/airline-support-outcomes/axes.json`'s 9 axes -- judge that claim, and that claim only.

Evidence you may use: the conversation (`agent_interaction.messages` -- customer and agent turns, tool calls and their results, in order) and the airline policy (`airline-data/policy.md`, passed to you as text). You are not given, and must not look for, any graded outcome or answer key.

Answer with exactly one verdict:

- `met` -- the transcript shows the criterion was satisfied.
- `not_met` -- the transcript shows it was not.
- `not_evaluable` -- the transcript does not contain enough evidence to decide either way. Use this only when the evidence genuinely is not there, not as a hedge.

Cite the specific turns and tool results you relied on.
