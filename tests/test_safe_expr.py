"""Unit tests for scripts/safe_expr.py's restricted expression grammar."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

from safe_expr import ExprError, eval_expr  # noqa: E402


class Literals(unittest.TestCase):
    def test_numbers_strings_bools_none(self):
        self.assertEqual(eval_expr("1", {}), 1)
        self.assertEqual(eval_expr("1.5", {}), 1.5)
        self.assertEqual(eval_expr("'x'", {}), "x")
        self.assertIs(eval_expr("True", {}), True)
        self.assertIs(eval_expr("None", {}), None)


class Names(unittest.TestCase):
    def test_name_looked_up_in_row(self):
        self.assertEqual(eval_expr("amount", {"amount": 42}), 42)

    def test_missing_name_is_none_not_an_error(self):
        self.assertIsNone(eval_expr("amount", {}))


class Comparisons(unittest.TestCase):
    def test_equality(self):
        self.assertTrue(eval_expr("amount == 42", {"amount": 42}))
        self.assertFalse(eval_expr("amount == 42", {"amount": 1}))

    def test_ordering(self):
        self.assertTrue(eval_expr("amount < 0", {"amount": -5}))
        self.assertFalse(eval_expr("amount < 0", {"amount": 5}))

    def test_ordering_against_a_missing_field_is_an_error_not_a_guess(self):
        with self.assertRaises(ExprError):
            eval_expr("amount < 0", {})

    def test_equality_against_a_missing_field_is_false_not_an_error(self):
        # == is a safe default to leave total (None == 42 is unambiguously False),
        # unlike ordering, which has no sane answer for an absent value.
        self.assertFalse(eval_expr("amount == 42", {}))

    def test_in_and_not_in(self):
        self.assertTrue(eval_expr("amount in [1, 2, 3]", {"amount": 2}))
        self.assertFalse(eval_expr("amount in [1, 2, 3]", {"amount": 9}))
        self.assertTrue(eval_expr("amount not in [1, 2, 3]", {"amount": 9}))

    def test_in_against_a_missing_field_raises_exprerror_not_a_bare_typeerror(self):
        # desk-review finding: "x in y" where y is a missing (None) field used
        # to raise an uncaught TypeError instead of this module's own ExprError.
        with self.assertRaises(ExprError):
            eval_expr("x in y", {"x": 1})
        with self.assertRaises(ExprError):
            eval_expr("x not in y", {"x": 1})

    def test_in_against_a_non_container_value_raises_exprerror(self):
        with self.assertRaises(ExprError):
            eval_expr("x in y", {"x": 1, "y": 5})

    def test_chained_comparison_is_refused(self):
        with self.assertRaises(ExprError):
            eval_expr("0 < amount < 10", {"amount": 5})


class BooleanCombinators(unittest.TestCase):
    def test_and_or_not(self):
        self.assertTrue(eval_expr("a and b", {"a": True, "b": True}))
        self.assertFalse(eval_expr("a and b", {"a": True, "b": False}))
        self.assertTrue(eval_expr("a or b", {"a": False, "b": True}))
        self.assertFalse(eval_expr("not a", {"a": True}))


class Arithmetic(unittest.TestCase):
    def test_basic_ops(self):
        self.assertEqual(eval_expr("a + b", {"a": 2, "b": 3}), 5)
        self.assertEqual(eval_expr("a - b", {"a": 2, "b": 3}), -1)
        self.assertEqual(eval_expr("a * 2", {"a": 3}), 6)
        self.assertEqual(eval_expr("a / 2", {"a": 10}), 5)
        self.assertEqual(eval_expr("-a", {"a": 3}), -3)

    def test_threshold_referencing_another_metric(self):
        self.assertTrue(eval_expr("cancellation_count <= conversation_count * 0.5",
                                   {"cancellation_count": 4, "conversation_count": 10}))
        self.assertFalse(eval_expr("cancellation_count <= conversation_count * 0.5",
                                    {"cancellation_count": 6, "conversation_count": 10}))

    def test_arithmetic_over_a_missing_field_is_an_error(self):
        with self.assertRaises(ExprError):
            eval_expr("a + 1", {})

    def test_arithmetic_over_incompatible_types_raises_exprerror_not_typeerror(self):
        # claude-security finding, this job: a sealed record's field can be
        # any JSON scalar type -- "amount": "n/a" where a spec expects a
        # number used to crash with a bare TypeError.
        with self.assertRaises(ExprError):
            eval_expr("a + 1", {"a": "n/a"})
        with self.assertRaises(ExprError):
            eval_expr("a / 2", {"a": "n/a"})

    def test_ordering_over_incompatible_types_raises_exprerror_not_typeerror(self):
        with self.assertRaises(ExprError):
            eval_expr("a < 1", {"a": "n/a"})
        with self.assertRaises(ExprError):
            eval_expr("a >= 1", {"a": "n/a"})

    def test_unary_minus_over_a_non_numeric_value_raises_exprerror(self):
        with self.assertRaises(ExprError):
            eval_expr("-a", {"a": "n/a"})


class Refusals(unittest.TestCase):
    def test_calls_are_refused(self):
        with self.assertRaises(ExprError):
            eval_expr("len([1,2,3])", {})

    def test_attribute_access_is_refused(self):
        with self.assertRaises(ExprError):
            eval_expr("a.b", {"a": {"b": 1}})

    def test_subscript_is_refused(self):
        with self.assertRaises(ExprError):
            eval_expr("a[0]", {"a": [1, 2]})

    def test_not_an_expression_at_all(self):
        with self.assertRaises(ExprError):
            eval_expr("import os", {})

    def test_lambda_is_refused(self):
        with self.assertRaises(ExprError):
            eval_expr("(lambda: 1)()", {})


if __name__ == "__main__":
    unittest.main()
