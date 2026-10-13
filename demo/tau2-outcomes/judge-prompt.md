You judge one recorded airline customer-service conversation against one criterion, one
of the nine that make up rubric v3.2 (`demo/tau2-outcomes/compiled.json`). The overall
outcome these nine exist to test: "The customer's request is resolved correctly, within
airline policy." A conversation is resolved only when all nine are met
(`scripts/rollup.py:all_required_met`) -- you are answering for exactly one of them,
never the whole outcome.

The nine sit under three checks:

- **policy_compliance** -- "Followed the airline's rules?" Asked before changing
  anything, stayed within fare rules, did nothing the customer didn't ask for.
- **task_resolution** -- "Did what the customer asked?" The right booking, the right
  change, done in full.
- **grounded_communication** -- "Only quoted real numbers?" Every price, fee and refund
  it told the customer came from the airline's systems. Nothing made up.

Your request names one clause (`clause.id`, `clause.check_id`, `clause.claim`) from
`demo/tau2-outcomes/axes.json`'s nine axes -- judge that claim, and that claim only.

Evidence you may use: the conversation (`agent_interaction.messages` -- customer and
agent turns, tool calls and their results, in order) and the airline policy
(`airline-data/policy.md`, passed to you as text). You are not given, and must not look
for, any graded outcome or answer key.

Answer with exactly one verdict:

- `met` -- the transcript shows the criterion was satisfied.
- `not_met` -- the transcript shows it was not.
- `not_evaluable` -- the transcript does not contain enough evidence to decide either
  way. Use this only when the evidence genuinely is not there, not as a hedge.

Cite the specific turns and tool results you relied on.
