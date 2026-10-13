"""Unit tests for scripts/recompute.py's deterministic within_fare_rules checker --
the tier_switch seam run_daily.py uses in place of the (not yet built)
capsulectl-engine fold plugin when the within_fare_rules_recomputed switch is on.

The headline case: tau2:airline:task-1:trial-0, the real conversation the first live
run's audit flagged -- Jev certified
a cancellation ~29h after booking (outside the 24h window) as met .96. This test reads
that exact conversation out of airline-data/*.json (no fixture, no paraphrase) through
demo/backfill/backfill.py's own trim_message(), the same transform run_daily.py's book
would have applied, and asserts the checker calls it not_met.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "demo" / "backfill"))

from backfill import trim_message  # noqa: E402
from recompute import RECOMPUTE_CHECKS, check_within_fare_rules  # noqa: E402

POLICY_PATH = str(ROOT / "airline-data" / "policy.md")
DB_PATH = str(ROOT / "airline-data" / "db.json")
RESULTS_FILE = ROOT / "airline-data" / "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json"


def _real_conversation(task_id, trial=0):
    data = json.loads(RESULTS_FILE.read_text())
    for sim in data["simulations"]:
        if str(sim.get("task_id")) == str(task_id) and sim.get("trial") == trial:
            return [trim_message(m) for m in sim["messages"]]
    raise AssertionError(f"no simulation for task_id={task_id!r} trial={trial!r} in {RESULTS_FILE}")


def _request(messages, policy=POLICY_PATH, booking_db=DB_PATH):
    return {"clause": {"id": "policy_compliance.within_fare_rules"}, "case": {},
            "agent_interaction": {"messages": messages}, "policy": policy, "booking_db": booking_db}


class RegistryTest(unittest.TestCase):
    def test_within_fare_rules_is_registered(self):
        self.assertIn("policy_compliance.within_fare_rules", RECOMPUTE_CHECKS)
        self.assertIs(RECOMPUTE_CHECKS["policy_compliance.within_fare_rules"], check_within_fare_rules)


class CancellationOutsideFareRules(unittest.TestCase):
    """tau2:airline:task-1:trial-0: economy, no insurance, cancelled ~29h after
    booking (outside the policy's 24h window). The agent told the customer "within
    24 hours" and Jev believed it (met .96) -- the live-run audit finding this
    checker exists to catch."""

    def test_real_task_1_conversation_is_flagged_not_met(self):
        messages = _real_conversation(task_id="1")
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_met", answer["rationale"])
        self.assertIn("Q69X3R", answer["rationale"])
        self.assertIn("within_24h", answer["rationale"])

    def test_a_compliant_cancel_within_24_hours_is_met(self):
        messages = [
            {"role": "user", "content": "please cancel"},
            {"role": "assistant", "content": "confirming the cancellation",
             "tool_calls": [{"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "ABC123"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps({
                "reservation_id": "ABC123", "cabin": "economy", "insurance": "no",
                "created_at": "2024-05-15T10:00:00",  # policy current time is 2024-05-15 15:00:00 -- 5h later
                "flights": [{"flight_number": "HAT001", "date": "2024-05-20"}],
            })},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "met", answer["rationale"])

    def test_business_cabin_cancel_outside_24h_is_still_met(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "BIZ1"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps({
                "reservation_id": "BIZ1", "cabin": "business", "insurance": "no",
                "created_at": "2024-01-01T00:00:00", "flights": [],
            })},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "met", answer["rationale"])

    def test_missing_created_at_gives_not_evaluable(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "NOCA"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps({
                "reservation_id": "NOCA", "cabin": "economy", "insurance": "no", "flights": [],
            })},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_evaluable", answer["rationale"])

    def test_unreadable_policy_path_gives_not_evaluable(self):
        messages = [{"role": "user", "content": "hi"}]
        answer = check_within_fare_rules(_request(messages, policy="/no/such/policy.md"))
        self.assertEqual(answer["verdict"], "not_evaluable")

    def test_malformed_tool_result_fails_closed_instead_of_crashing(self):
        # a non-string flight_number (e.g. a list) breaks the flights[flight_number]
        # dict lookup in scripts/airline_facts.flight_status() with a TypeError --
        # the conversation is attacker-influenceable content, so this must come back
        # not_evaluable, never an uncaught exception that would take down the whole run.
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "R1"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps({
                "reservation_id": "R1", "cabin": "economy", "insurance": "no",
                "created_at": "2024-01-01T00:00:00",
                "flights": [{"flight_number": ["not", "a", "string"], "date": "2024-05-20"}],
            })},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_evaluable")

    def test_insurance_covered_reason_must_be_stated_near_the_cancellation(self):
        # an unrelated health/weather word earlier in the conversation (small talk
        # about an old, different flight) must not retroactively excuse a cancellation
        # outside the 24h window that insurance="yes" alone doesn't cover.
        messages = [
            {"role": "user", "content": "By the way, the weather on my last trip to Denver was awful."},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "lookup", "name": "get_reservation_details", "arguments": {"reservation_id": "R1"}}]},
            {"role": "tool", "tool_call_id": "lookup", "content": json.dumps(
                {"reservation_id": "R1", "cabin": "economy", "insurance": "yes",
                 "created_at": "2024-01-01T00:00:00", "flights": []})},
            {"role": "user", "content": "I just want to cancel my upcoming trip, plans changed."},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "R1"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
                {"reservation_id": "R1", "cabin": "economy", "insurance": "yes",
                 "created_at": "2024-01-01T00:00:00", "flights": []})},
        ]
        answer = check_within_fare_rules(_request(messages, policy=POLICY_PATH))
        self.assertEqual(answer["verdict"], "not_met", answer["rationale"])

    def test_insurance_covered_reason_stated_right_before_the_cancellation_is_met(self):
        messages = [
            {"role": "user", "content": "I was hospitalized and need to cancel my upcoming trip."},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "R1"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
                {"reservation_id": "R1", "cabin": "economy", "insurance": "yes",
                 "created_at": "2024-01-01T00:00:00", "flights": []})},
        ]
        answer = check_within_fare_rules(_request(messages, policy=POLICY_PATH))
        self.assertEqual(answer["verdict"], "met", answer["rationale"])

    def test_no_relevant_action_is_vacuously_met(self):
        messages = [{"role": "user", "content": "what's my reservation status?"},
                    {"role": "assistant", "content": "let me check"}]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "met")
        self.assertIn("no cancellation", answer["rationale"])


class BasicEconomyFlightChange(unittest.TestCase):
    def test_modifying_a_basic_economy_reservation_is_not_met(self):
        messages = [
            {"role": "tool", "tool_call_id": "lookup", "content": json.dumps(
                {"reservation_id": "BE1", "cabin": "basic_economy"})},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "update_reservation_flights",
                 "arguments": {"reservation_id": "BE1", "cabin": "basic_economy", "flights": []}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
                {"reservation_id": "BE1", "cabin": "basic_economy"})},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_met", answer["rationale"])
        self.assertIn("basic_economy", answer["rationale"])

    def test_modifying_an_economy_reservation_is_met(self):
        messages = [
            {"role": "tool", "tool_call_id": "lookup", "content": json.dumps(
                {"reservation_id": "EC1", "cabin": "economy"})},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "update_reservation_flights",
                 "arguments": {"reservation_id": "EC1", "cabin": "economy", "flights": []}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
                {"reservation_id": "EC1", "cabin": "economy"})},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "met", answer["rationale"])


class CertificateWithoutAccompanyingAction(unittest.TestCase):
    """tau2:airline:task-2:trial-0's real shape, reproduced as a fixture: a $50
    delay gesture with no change or cancel anywhere in the conversation."""

    def test_fifty_dollar_gesture_with_no_change_or_cancel_is_not_met(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "send_certificate", "arguments": {"user_id": "u1", "amount": 50}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "Certificate added."},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_met", answer["rationale"])

    def test_fifty_dollar_gesture_alongside_a_cancel_is_met(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "cancel_reservation", "arguments": {"reservation_id": "R1"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps(
                {"reservation_id": "R1", "cabin": "business", "insurance": "no", "flights": []})},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c2", "name": "send_certificate", "arguments": {"user_id": "u1", "amount": 50}}]},
            {"role": "tool", "tool_call_id": "c2", "content": "Certificate added."},
        ]
        answer = check_within_fare_rules(_request(messages))
        # the cancel itself is eligible (business cabin), the certificate has its
        # required accompanying action -- both sub-checks pass.
        self.assertEqual(answer["verdict"], "met", answer["rationale"])

    def test_hundred_dollar_gesture_needs_no_accompanying_action(self):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "send_certificate", "arguments": {"user_id": "u1", "amount": 100}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "Certificate added."},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "met", answer["rationale"])

    def test_the_real_task_2_certificate_is_also_flagged(self):
        messages = _real_conversation(task_id="2")
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_met", answer["rationale"])

    def test_hundred_dollar_gesture_for_two_passengers_is_the_fifty_dollar_gesture(self):
        """$100 for a 2-passenger reservation is $50 x passengers, not $100 x
        passengers (that would be $200) -- the reservation's own passenger count
        disambiguates it, and with no accompanying change/cancel this is not_met."""
        messages = [
            {"role": "tool", "tool_call_id": "lookup", "content": json.dumps(
                {"reservation_id": "R2", "passengers": [{"first_name": "A"}, {"first_name": "B"}]})},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "send_certificate", "arguments": {"user_id": "u1", "amount": 100}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "Certificate added."},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_met", answer["rationale"])

    def test_two_hundred_dollar_gesture_for_two_passengers_needs_no_accompanying_action(self):
        """$200 for a 2-passenger reservation is unambiguously $100 x passengers
        (the $50 gesture would be $100 for 2 passengers, not $200)."""
        messages = [
            {"role": "tool", "tool_call_id": "lookup", "content": json.dumps(
                {"reservation_id": "R2", "passengers": [{"first_name": "A"}, {"first_name": "B"}]})},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "send_certificate", "arguments": {"user_id": "u1", "amount": 200}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "Certificate added."},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "met", answer["rationale"])

    def test_amount_matching_both_gestures_across_two_reservation_sizes_is_not_evaluable(self):
        """$100 is consistent with the $100 gesture for a 1-passenger reservation and
        the $50 gesture for a 2-passenger reservation seen in the same conversation --
        genuinely ambiguous, not a guess."""
        messages = [
            {"role": "tool", "tool_call_id": "lookup1", "content": json.dumps(
                {"reservation_id": "R1", "passengers": [{"first_name": "A"}]})},
            {"role": "tool", "tool_call_id": "lookup2", "content": json.dumps(
                {"reservation_id": "R2", "passengers": [{"first_name": "B"}, {"first_name": "C"}]})},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "name": "send_certificate", "arguments": {"user_id": "u1", "amount": 100}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "Certificate added."},
        ]
        answer = check_within_fare_rules(_request(messages))
        self.assertEqual(answer["verdict"], "not_evaluable", answer["rationale"])


if __name__ == "__main__":
    unittest.main()
