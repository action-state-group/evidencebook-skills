---
name: adjudicate-deal
description: Assist a deal's adjudicator. Gathers the case a party sent (the dispute, the books each side sent when asked and what they show), shows it plainly, opens the decision to the person who rules, and reports whether each party entered the ruling in its own records. Never decides a ruling. Use on the ARD demo's adjudicator window.
---
# Adjudicate a deal

> **Demo host, step A.** This skill runs today only on the ARD two-seller demo's host, whose adjudicator is its own
> capsulectl-deal profile, run by the demo operator (the host table at the end). Do not copy the
> demo host's tools into another host.

A buyer or a seller disputed one row of a deal whose agreement names this adjudicator. You show the person who
rules what the case holds. The ruling is theirs: you never decide it, suggest it, or record one they did not choose.

## Steps

1. **Show the case.** Which deal and which row; that each side was asked for its books, and which side answered and
   when (each answer is that side's own book and the copy it holds of the other side's); what those books show, in
   the records' own words (a seller's own signed delivery record, each side's statement on the row). Say which side
   did not answer.
2. **The person rules.** When the person says how to rule, open the decision. Its dialog is the only control: you
   cannot see or answer it. If the dialog is cancelled, nothing was ruled.
3. **Report the entries.** Whether each party entered the ruling in its own records, as the books they sent show.

## Rules

- Say it plainly: this adjudicator is run by the operator, who also runs every party here, so it is not
  independent of them.
- A ruling against a side rests only on records that side signed itself (Steven, ops u211). A side that did not
  answer is read from the records it signed that the other side holds; when none of its records was read, the ruling
  cannot go against it, and capsulectl refuses one that would.
- Never call a party dishonest or say it failed. Say what the ruling found: the row was not met, against that side.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent listing, no tool search
  except to load your own tools.

## Host table

| Step | On the demo host (step A) | On a capsule host |
|---|---|---|
| 1 Show the case | `ard_case`: the request to each side, their `deal respond` answers | the hosted adjudicator's intake (evidencebook#861 PR 3) |
| 2 Record the ruling | `ard_rule`: the presenter's dialog, then `deal ruling --answer` and the stamp | `deal ruling --answer` |
| 3 Report the entries | `ard_case_activity` | `deal ruling entries` |

## On the demo host

- Call one tool per message from the person, and only the one they ask for. After it returns, say in at most two
  short plain sentences what it showed. Do not repeat its output: the audience reads it in the tool call.
- Never name a tool to the person.
