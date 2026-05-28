"""
Unit Tests — Finance Calculator Service
=========================================

These are pure function tests — no database, no HTTP, no async.
All calculator functions are stateless: same input → same output.

This is the ideal case for unit tests: fast, isolated, deterministic.

We verify:
  1. Correct mathematical results (verified manually against known values)
  2. Edge cases (zero rates, zero years, zero interest)
  3. Decimal precision (results are rounded to 2 decimal places)
  4. Type correctness (all numeric results are Decimal)
"""

from __future__ import annotations

from decimal import Decimal

from app.calculator.service import (
    budget_planner,
    compound_interest,
    loan_emi,
    savings_projection,
    sip_calculator,
    tax_estimate,
)

# =============================================================================
# COMPOUND INTEREST TESTS
# =============================================================================


class TestCompoundInterest:
    """Tests for compound_interest()."""

    def test_basic_calculation(self):
        """
        $10,000 at 8% per year, compounded monthly, for 10 years.
        Formula: A = 10000 × (1 + 0.08/12)^(12×10)
        Expected: ~$22,196.40
        """
        result = compound_interest(
            principal=Decimal("10000"),
            annual_rate_pct=Decimal("8"),
            years=10,
        )
        assert result["principal"] == Decimal("10000.00")
        assert result["total_amount"] == Decimal("22196.40")
        assert result["interest_earned"] == Decimal("12196.40")

    def test_annual_compounding(self):
        """
        $1,000 at 10% per year, compounded annually, for 1 year.
        Should be exactly: 1000 × 1.10 = $1,100.00
        """
        result = compound_interest(
            principal=Decimal("1000"),
            annual_rate_pct=Decimal("10"),
            years=1,
            compounds_per_year=1,
        )
        assert result["total_amount"] == Decimal("1100.00")
        assert result["interest_earned"] == Decimal("100.00")

    def test_zero_interest_rate(self):
        """At 0% interest, amount equals principal."""
        result = compound_interest(
            principal=Decimal("5000"),
            annual_rate_pct=Decimal("0"),
            years=10,
        )
        assert result["total_amount"] == Decimal("5000.00")
        assert result["interest_earned"] == Decimal("0.00")

    def test_one_year_monthly_compounding(self):
        """
        $1,000 at 12% per year, monthly compounding, 1 year.
        A = 1000 × (1 + 0.12/12)^12 = 1000 × (1.01)^12 ≈ $1,126.83
        """
        result = compound_interest(
            principal=Decimal("1000"),
            annual_rate_pct=Decimal("12"),
            years=1,
        )
        assert result["total_amount"] == Decimal("1126.83")

    def test_returns_all_expected_keys(self):
        """Result contains all expected keys."""
        result = compound_interest(
            principal=Decimal("1000"),
            annual_rate_pct=Decimal("5"),
            years=5,
        )
        expected_keys = {
            "principal",
            "total_amount",
            "interest_earned",
            "annual_rate_pct",
            "effective_annual_rate_pct",
            "years",
            "compounds_per_year",
        }
        assert set(result.keys()) == expected_keys

    def test_result_values_are_decimal(self):
        """All monetary result values are Decimal (not float)."""
        result = compound_interest(
            principal=Decimal("1000"),
            annual_rate_pct=Decimal("5"),
            years=3,
        )
        for key in ("principal", "total_amount", "interest_earned"):
            assert isinstance(result[key], Decimal), f"{key} should be Decimal"

    def test_effective_annual_rate_higher_than_nominal(self):
        """
        For monthly compounding, EAR > nominal rate.
        12% nominal compounded monthly → EAR ≈ 12.68%
        """
        result = compound_interest(
            principal=Decimal("1000"),
            annual_rate_pct=Decimal("12"),
            years=1,
        )
        assert result["effective_annual_rate_pct"] > Decimal("12")

    def test_quarterly_compounding(self):
        """$5,000 at 6% quarterly for 2 years."""
        result = compound_interest(
            principal=Decimal("5000"),
            annual_rate_pct=Decimal("6"),
            years=2,
            compounds_per_year=4,
        )
        # A = 5000 × (1 + 0.06/4)^(4×2) = 5000 × (1.015)^8 ≈ $5,632.46
        assert result["total_amount"] == Decimal("5632.46")


# =============================================================================
# LOAN EMI TESTS
# =============================================================================


class TestLoanEMI:
    """Tests for loan_emi()."""

    def test_basic_emi_calculation(self):
        """
        $100,000 at 12% for 120 months.
        r = 12/12/100 = 0.01
        EMI = 100000 × 0.01 × (1.01)^120 / ((1.01)^120 - 1) ≈ $1,434.71
        """
        result = loan_emi(
            principal=Decimal("100000"),
            annual_rate_pct=Decimal("12"),
            tenure_months=120,
        )
        assert result["emi"] == Decimal("1434.71")

    def test_zero_interest_emi(self):
        """At 0% interest, EMI = principal / months."""
        result = loan_emi(
            principal=Decimal("12000"),
            annual_rate_pct=Decimal("0"),
            tenure_months=12,
        )
        assert result["emi"] == Decimal("1000.00")
        assert result["total_interest"] == Decimal("0.00")

    def test_total_payment_equals_emi_times_months(self):
        """
        Total payment ≈ EMI × tenure_months.

        Why the tolerance?
        EMI is rounded to 2 decimal places. When multiplied by many months,
        rounding error compounds. For 60 months × up to 0.005 per rounding
        = up to $0.30 total drift. We allow $0.50 tolerance to be safe.
        """
        result = loan_emi(
            principal=Decimal("50000"),
            annual_rate_pct=Decimal("8"),
            tenure_months=60,
        )
        expected = result["emi"] * result["tenure_months"]
        diff = abs(result["total_payment"] - expected)
        # Rounding accumulates: up to 0.005 per month × 60 months = $0.30
        assert diff < Decimal("0.50")

    def test_total_interest_positive(self):
        """Total interest is positive for any non-zero rate."""
        result = loan_emi(
            principal=Decimal("20000"),
            annual_rate_pct=Decimal("10"),
            tenure_months=24,
        )
        assert result["total_interest"] > Decimal("0")

    def test_returns_amortization_schedule(self):
        """Amortization schedule contains first 3 months."""
        result = loan_emi(
            principal=Decimal("10000"),
            annual_rate_pct=Decimal("12"),
            tenure_months=24,
        )
        schedule = result["first_3_months"]
        assert len(schedule) == 3
        assert schedule[0]["month"] == 1
        assert schedule[1]["month"] == 2
        assert schedule[2]["month"] == 3

    def test_amortization_principal_plus_interest_equals_emi(self):
        """
        For each month in amortization:
        principal_part + interest_part ≈ emi (within rounding)
        """
        result = loan_emi(
            principal=Decimal("15000"),
            annual_rate_pct=Decimal("9"),
            tenure_months=36,
        )
        for month in result["first_3_months"]:
            total = month["principal_part"] + month["interest_part"]
            diff = abs(total - month["emi"])
            assert diff < Decimal(
                "0.02"
            ), f"Month {month['month']}: {total} ≠ {month['emi']}"

    def test_returns_all_expected_keys(self):
        """Result contains all expected keys."""
        result = loan_emi(
            principal=Decimal("10000"),
            annual_rate_pct=Decimal("12"),
            tenure_months=12,
        )
        expected_keys = {
            "principal",
            "annual_rate_pct",
            "tenure_months",
            "emi",
            "total_payment",
            "total_interest",
            "interest_to_principal_ratio",
            "first_3_months",
        }
        assert set(result.keys()) == expected_keys

    def test_short_tenure(self):
        """1-month loan works (returns 1-item amortization)."""
        result = loan_emi(
            principal=Decimal("1000"),
            annual_rate_pct=Decimal("12"),
            tenure_months=1,
        )
        assert result["emi"] > Decimal("0")
        assert len(result["first_3_months"]) == 1


# =============================================================================
# SIP CALCULATOR TESTS
# =============================================================================


class TestSIPCalculator:
    """Tests for sip_calculator()."""

    def test_basic_sip_calculation(self):
        """
        $1,000/month at 12%/year for 10 years.
        Total invested: $120,000
        Expected FV: significantly more than $120,000 due to compounding
        """
        result = sip_calculator(
            monthly_investment=Decimal("1000"),
            annual_rate_pct=Decimal("12"),
            years=10,
        )
        total_invested = Decimal("1000") * 12 * 10  # 120,000
        assert result["total_invested"] == Decimal("120000.00")
        assert result["future_value"] > total_invested  # Compounding adds value

    def test_zero_rate_equals_total_invested(self):
        """At 0% return, future value = total invested."""
        result = sip_calculator(
            monthly_investment=Decimal("500"),
            annual_rate_pct=Decimal("0"),
            years=5,
        )
        expected_total = Decimal("500") * 12 * 5  # 30,000
        assert result["future_value"] == Decimal("30000.00")
        assert result["wealth_gained"] == Decimal("0.00")

    def test_wealth_gained_positive_for_nonzero_rate(self):
        """Wealth gained > 0 when rate > 0."""
        result = sip_calculator(
            monthly_investment=Decimal("200"),
            annual_rate_pct=Decimal("8"),
            years=20,
        )
        assert result["wealth_gained"] > Decimal("0")

    def test_return_on_investment_positive(self):
        """ROI% is positive when rate > 0."""
        result = sip_calculator(
            monthly_investment=Decimal("500"),
            annual_rate_pct=Decimal("10"),
            years=15,
        )
        assert result["return_on_investment_pct"] > Decimal("0")

    def test_longer_duration_yields_more(self):
        """Investing for longer periods yields more (compounding effect)."""
        short = sip_calculator(
            monthly_investment=Decimal("500"),
            annual_rate_pct=Decimal("10"),
            years=10,
        )
        long = sip_calculator(
            monthly_investment=Decimal("500"),
            annual_rate_pct=Decimal("10"),
            years=20,
        )
        assert long["future_value"] > short["future_value"]

    def test_returns_all_expected_keys(self):
        """Result contains all expected keys."""
        result = sip_calculator(
            monthly_investment=Decimal("100"),
            annual_rate_pct=Decimal("8"),
            years=5,
        )
        expected_keys = {
            "monthly_investment",
            "annual_rate_pct",
            "years",
            "total_invested",
            "future_value",
            "wealth_gained",
            "return_on_investment_pct",
        }
        assert set(result.keys()) == expected_keys


# =============================================================================
# SAVINGS PROJECTION TESTS
# =============================================================================


class TestSavingsProjection:
    """Tests for savings_projection()."""

    def test_basic_projection(self):
        """
        $10,000 savings, $500/month contribution, 7% return, 10 years.
        Should grow significantly beyond contributions.
        """
        result = savings_projection(
            current_savings=Decimal("10000"),
            monthly_contribution=Decimal("500"),
            annual_return_pct=Decimal("7"),
            years=10,
        )
        total_contributed = Decimal("500") * 12 * 10  # $60,000
        assert result["total_contributed"] == Decimal("60000.00")
        # Nominal future value should be more than total + initial savings
        assert result["nominal_future_value"] > total_contributed + Decimal("10000")

    def test_real_value_less_than_nominal(self):
        """Real (inflation-adjusted) value is always less than nominal."""
        result = savings_projection(
            current_savings=Decimal("5000"),
            monthly_contribution=Decimal("300"),
            annual_return_pct=Decimal("8"),
            years=20,
        )
        assert result["real_future_value"] < result["nominal_future_value"]

    def test_zero_inflation_real_equals_nominal(self):
        """At 0% inflation, real value equals nominal value."""
        result = savings_projection(
            current_savings=Decimal("1000"),
            monthly_contribution=Decimal("100"),
            annual_return_pct=Decimal("5"),
            years=5,
            annual_inflation_pct=Decimal("0"),
        )
        assert result["real_future_value"] == result["nominal_future_value"]

    def test_inflation_erosion_positive(self):
        """Inflation erosion (difference) is positive when inflation > 0."""
        result = savings_projection(
            current_savings=Decimal("10000"),
            monthly_contribution=Decimal("500"),
            annual_return_pct=Decimal("8"),
            years=10,
            annual_inflation_pct=Decimal("3"),
        )
        assert result["inflation_erosion"] > Decimal("0")

    def test_returns_all_expected_keys(self):
        """Result contains all expected keys."""
        result = savings_projection(
            current_savings=Decimal("1000"),
            monthly_contribution=Decimal("100"),
            annual_return_pct=Decimal("5"),
            years=3,
        )
        expected_keys = {
            "current_savings",
            "monthly_contribution",
            "annual_return_pct",
            "annual_inflation_pct",
            "years",
            "total_contributed",
            "nominal_future_value",
            "real_future_value",
            "inflation_erosion",
        }
        assert set(result.keys()) == expected_keys


# =============================================================================
# TAX ESTIMATE TESTS
# =============================================================================


class TestTaxEstimate:
    """Tests for tax_estimate()."""

    def test_income_below_deduction_no_tax(self):
        """
        Income less than the standard deduction ($14,600) → no tax.
        Taxable income = 0.
        """
        result = tax_estimate(gross_income=Decimal("10000"))
        assert result["total_tax"] == Decimal("0.00")
        assert result["taxable_income"] == Decimal("0.00")

    def test_standard_deduction_applied(self):
        """Standard deduction is subtracted from gross income."""
        result = tax_estimate(gross_income=Decimal("50000"))
        expected_taxable = Decimal("50000") - Decimal("14600")  # $35,400
        assert result["taxable_income"] == expected_taxable

    def test_income_100k_effective_rate(self):
        """
        $100,000 income (single).
        Taxable = $100,000 - $14,600 = $85,400
        Tax = 10% on first $11,600 + 12% on $11,601-$47,150 + 22% on $47,151-$85,400
            = $1,160 + $4,266 + $8,415.78 = $13,841.78
        Effective rate = 13,841.78 / 100,000 = 13.84%
        """
        result = tax_estimate(gross_income=Decimal("100000"))
        assert result["total_tax"] > Decimal("0")
        # Effective rate should be less than 22% (the marginal rate)
        assert result["effective_rate_pct"] < Decimal("22")
        # Should be between 10-20% (reasonable range)
        assert Decimal("10") < result["effective_rate_pct"] < Decimal("20")

    def test_progressive_tax_structure(self):
        """
        Higher income → higher effective rate (but never exceeds marginal rate).
        The bracket_breakdown shows each bracket's contribution.
        """
        result_50k = tax_estimate(gross_income=Decimal("50000"))
        result_200k = tax_estimate(gross_income=Decimal("200000"))
        # Higher income → higher effective rate
        assert result_200k["effective_rate_pct"] > result_50k["effective_rate_pct"]

    def test_additional_deductions_reduce_tax(self):
        """Additional deductions reduce taxable income and thus tax."""
        base = tax_estimate(gross_income=Decimal("80000"))
        with_deduction = tax_estimate(
            gross_income=Decimal("80000"),
            additional_deductions=Decimal("10000"),
        )
        assert with_deduction["total_tax"] < base["total_tax"]

    def test_take_home_equals_income_minus_tax(self):
        """take_home = gross_income - total_tax."""
        result = tax_estimate(gross_income=Decimal("75000"))
        expected_take_home = result["gross_income"] - result["total_tax"]
        assert result["take_home"] == expected_take_home

    def test_bracket_breakdown_provided(self):
        """Tax bracket breakdown is a list of dicts."""
        result = tax_estimate(gross_income=Decimal("100000"))
        assert isinstance(result["bracket_breakdown"], list)
        assert len(result["bracket_breakdown"]) > 0
        for bracket in result["bracket_breakdown"]:
            assert "bracket_pct" in bracket
            assert "taxable_amount" in bracket
            assert "tax" in bracket

    def test_zero_income(self):
        """Zero income → zero tax, zero effective rate."""
        result = tax_estimate(gross_income=Decimal("0"))
        assert result["total_tax"] == Decimal("0.00")
        assert result["effective_rate_pct"] == Decimal("0.00")


# =============================================================================
# BUDGET PLANNER TESTS
# =============================================================================


class TestBudgetPlanner:
    """Tests for budget_planner()."""

    def test_50_30_20_rule(self):
        """
        $5,000/month:
        Needs (50%) = $2,500
        Wants (30%) = $1,500
        Savings (20%) = $1,000
        """
        result = budget_planner(monthly_income=Decimal("5000"))
        assert result["needs_50pct"] == Decimal("2500.00")
        assert result["wants_30pct"] == Decimal("1500.00")
        assert result["savings_20pct"] == Decimal("1000.00")

    def test_sums_to_monthly_income(self):
        """Needs + wants + savings = monthly income (±rounding)."""
        result = budget_planner(monthly_income=Decimal("7500"))
        total = result["needs_50pct"] + result["wants_30pct"] + result["savings_20pct"]
        diff = abs(total - Decimal("7500"))
        assert diff <= Decimal("0.02")

    def test_proportions_correct(self):
        """Verify 50/30/20 proportions for any income."""
        income = Decimal("3333.33")
        result = budget_planner(monthly_income=income)
        # needs should be ~50% of income
        assert abs(result["needs_50pct"] / income - Decimal("0.50")) < Decimal("0.001")

    def test_returns_category_lists(self):
        """Budget planner returns category lists for needs, wants, savings."""
        result = budget_planner(monthly_income=Decimal("4000"))
        assert isinstance(result["needs_categories"], list)
        assert isinstance(result["wants_categories"], list)
        assert isinstance(result["savings_categories"], list)
        assert len(result["needs_categories"]) > 0
        assert "Rent/Mortgage" in result["needs_categories"]

    def test_high_income_scales_correctly(self):
        """High income scales proportionally."""
        result = budget_planner(monthly_income=Decimal("20000"))
        assert result["savings_20pct"] == Decimal("4000.00")

    def test_returns_all_expected_keys(self):
        """Result contains all expected keys."""
        result = budget_planner(monthly_income=Decimal("5000"))
        expected_keys = {
            "monthly_income",
            "needs_50pct",
            "wants_30pct",
            "savings_20pct",
            "needs_categories",
            "wants_categories",
            "savings_categories",
        }
        assert set(result.keys()) == expected_keys
