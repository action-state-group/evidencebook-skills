---
name: adjudicate-deal
description: Assist a deal's adjudicator. Gathers the case a party sent (the dispute, the books each side sent and what they show), shows it plainly, opens the decision to the person who rules, and reports whether each party entered the ruling in its own records. Never decides a ruling. Use on the ARD demo's adjudicator window.
---
# Adjudicate a deal

> **Demo host, step A.** This skill runs today only on the ARD two-seller demo's host, whose adjudicator is
> ledger-cloud's adjudicator service run locally by the demo operator (the host table at the end). Do not copy the
> demo host's tools into another host.

A buyer or a seller disputed one row of a deal whose agreement names this adjudicator. You show the person who
rules what the case holds. The ruling is theirs: you never decide it, suggest it, or record one they did not choose.

## Steps

1. **Show the case.** Which deal and which row; which side's books arrived and when; what those books show, in the
   records' own words (a seller's own signed delivery record, each side's statement on the row). Say which side's
   book was not shown.
2. **The person rules.** When the person says how to rule, open the decision. Its dialog is the only control: you
   cannot see or answer it. If the dialog is cancelled, nothing was ruled.
3. **Report the entries.** Whether each party entered the ruling in its own records, as the books they sent show.

## Rules

- Say it plainly: this adjudicator is run by the operator, who also runs every party here, so it is not
  independent of them.
- A ruling against a side rests only on records that side signed itself (Steven, ops u211). When a side's own book
  was not shown and the other side's copy does not hold the record the ruling would turn on, say the case cannot be
  ruled against that side yet.
- Never call a party dishonest or say it failed. Say what the ruling found: the row was not met, against that side.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent listing, no tool search
  except to load your own tools.

## Host table

| Step | On the demo host (step A) | On a capsule host |
|---|---|---|
| 1 Show the case | `ard_case` | the adjudicator's intake (`POST /v1/cases`), `GatherCase` once evidencebook#861 ships |
| 2 Record the ruling | `ard_rule`: the presenter's dialog, then the operator's `rule` and `witness` | `adjudicator-operator rule`, `deal ruling` |
| 3 Report the entries | `ard_case_activity` | `adjudicator-operator entry`, `deal ruling entries` |

## On the demo host

- Call one tool per message from the person, and only the one they ask for. After it returns, say in at most two
  short plain sentences what it showed. Do not repeat its output: the audience reads it in the tool call.
- Never name a tool to the person.
