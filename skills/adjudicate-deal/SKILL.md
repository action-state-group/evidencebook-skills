---
name: adjudicate-deal
description: Assist a deal's adjudicator. Shows the case a party sent (the dispute, the books each side sent when asked and what they show), what the adjudicator ruled on its own and why, or why it has not, and whether each party entered the ruling in its own records. Never decides a ruling. Use on the ARD demo's adjudicator window.
---
# Adjudicate a deal

> **Demo host, step A.** This skill runs today only on the ARD two-seller demo's host, whose adjudicator is its own
> capsulectl-deal profile, run by the demo operator (the five verbs' table at the end). Do not copy the
> demo host's tools into another host.

A buyer or a seller disputed one row of a deal whose agreement names this adjudicator. The adjudicator rules on its
own, with no person, under its published rules: when the side the ruling would go against has itself stated, in a
record it signed, that the row was not met, and has not stated otherwise since. Otherwise the case needs a person,
and nothing is ruled. You show what the case holds and what the adjudicator ruled and why. You never decide a ruling,
suggest one, or record one.

## Steps

1. **Show the case.** Which deal and which row; that each side was asked for its books, and which side answered and
   when (each answer is that side's own book and the copy it holds of the other side's); what those books show, in
   the records' own words (a seller's own signed delivery record, each side's statement on the row). Say which side
   did not answer.
2. **Show the ruling.** Show what the adjudicator ruled and why, or why it has not, under the line that it is not
   independent of the parties. These lines are the adjudicator's own: the person reads them as the tool printed them.
3. **Report the entries.** Whether each party entered the ruling in its own records, as the books they sent show.

## Rules

- The adjudicator is run by the operator, who also runs every party here, so it is not independent of them. Never
  say or suggest that this does not matter.
- A ruling against a side rests only on records that side signed itself (Steven, ops u211). A side that did not
  answer is read from the records it signed that the other side holds; when none of its records was read, the ruling
  cannot go against it, and capsulectl refuses one that would.
- Never call a party dishonest or say it failed. Say what the ruling found: the row was not met, against that side.
- Use only the tools of your own extension: no terminal, no file tools, no session or agent listing, no tool search
  except to load your own tools.

## The five verbs

This skill teaches five verbs and nothing else: **check** before you act, **record** what was done, **ask** the
other side for evidence, or answer when it asks, **verify** what you get, and **show** a card or a receipt. Each row maps a verb, at one
step, to the demo host's tool and to the capsule host's existing command.

| Verb | Step | On the demo host (step A) | On a capsule host |
|---|---|---|---|
| ask | 1 Ask each side for its books | `ard_case`: the request to each side, their `deal respond` answers | the hosted adjudicator's intake (evidencebook#861 PR 3) |
| show | 1 Show the case | `ard_case` | the hosted adjudicator's intake (evidencebook#861 PR 3) |
| show | 2 Show the ruling | `ard_ruling` | `deal ruling` (the ruling file it writes) |
| check | 2 Decide whether the books settle the row | the adjudicator's own window, with no person: `deal ruling check` | `deal ruling check` |
| record | 2 Record the ruling | the adjudicator's own window: `deal ruling --decided-by --answer` and the stamp; `ard_case` shows it | `deal ruling --decided-by --answer` |
| show | 3 Report the entries | `ard_case_activity` | `deal ruling entries` |

## On the demo host

- Every answer in this window is a tool's output, which the person reads as the tool printed it. For each message
  from the person, call one tool and write nothing of your own: the case for the case (step 1), the ruling for the
  ruling, its reason or the adjudicator's independence (step 2), at any point and in a reopened session too, and the
  entries for the entries (step 3). Never answer from an earlier output or in your own words. With Claude Code, the
  demo's window enforces this: each tool ends your turn, and your own text is not shown.
- Never name a tool to the person.
