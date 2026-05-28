"""
Integration Tests — Finance Calculator API
===========================================

Tests the calculator HTTP endpoints (POST-based, no auth required).

These are primarily smoke tests — verifying the endpoints are reachable,
accept valid inputs, reject invalid inputs, and return expected keys.

The mathematical correctness is tested in unit/test_calculator.py.

Key thing to test here:
  - Pydantic validation of HTTP request bodies
  - HTTP 200 for valid inputs
  - HTTP 422 for invalid inputs (negative values, missing fields, etc.)
  - Response shape (required keys present)
"""

from __future__ import annotations

from httpx import AsyncClient

# =============================================================================
# COMPOUND INTEREST ENDPOINT
# =============================================================================


class TestCompoundInterestEndpoint:
    """Tests for POST /api/v1/calculator/compound-interest."""

    async def test_basic_request_succeeds(self, client: AsyncClient):
        """Valid compound interest request returns 200."""
        resp = await client.post(
            "/api/v1/calculator/compound-interest",
            json={
                "principal": 10000,
                "annual_rate_pct": 8,
                "years": 10,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_amount" in data
        assert "interest_earned" in data
        assert "principal" in data

    async def test_result_values_match_expected(self, client: AsyncClient):
        """$10k at 8% for 10 years ≈ $22,196.40."""
        resp = await client.post(
            "/api/v1/calculator/compound-interest",
            json={"principal": 10000, "annual_rate_pct": 8, "years": 10},
        )
        data = resp.json()
        # Result comes as string (Decimal serialized)
        total = float(data["total_amount"])
        assert abs(total - 22196.40) < 1.0  # Within $1

    async def test_negative_principal_fails(self, client: AsyncClient):
        """Negative principal → 422 Validation Error."""
        resp = await client.post(
            "/api/v1/calculator/compound-interest",
            json={"principal": -1000, "annual_rate_pct": 8, "years": 10},
        )
        assert resp.status_code == 422

    async def test_very_small_rate_accepted(self, client: AsyncClient):
        """Very small positive rate (0.01%) is valid."""
        resp = await client.post(
            "/api/v1/calculator/compound-interest",
            json={"principal": 1000, "annual_rate_pct": 0.01, "years": 5},
        )
        assert resp.status_code == 200

    async def test_missing_required_fields_fails(self, client: AsyncClient):
        """Missing required fields → 422."""
        resp = await client.post(
            "/api/v1/calculator/compound-interest",
            json={"principal": 1000},  # Missing annual_rate_pct, years
        )
        assert resp.status_code == 422

    async def test_no_auth_required(self, client: AsyncClient):
        """Calculator endpoints require no authentication."""
        resp = await client.post(
            "/api/v1/calculator/compound-interest",
            json={"principal": 5000, "annual_rate_pct": 6, "years": 5},
        )
        assert resp.status_code == 200  # No auth needed


# =============================================================================
# LOAN EMI ENDPOINT
# =============================================================================


class TestLoanEMIEndpoint:
    """Tests for POST /api/v1/calculator/loan-emi."""

    async def test_basic_request_succeeds(self, client: AsyncClient):
        """Valid loan EMI request returns 200 with expected keys."""
        resp = await client.post(
            "/api/v1/calculator/loan-emi",
            json={
                "principal": 500000,
                "annual_rate_pct": 8.5,
                "tenure_months": 240,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "emi" in data
        assert "total_payment" in data
        assert "total_interest" in data
        assert "first_3_months" in data

    async def test_emi_is_positive(self, client: AsyncClient):
        """EMI value is always positive."""
        resp = await client.post(
            "/api/v1/calculator/loan-emi",
            json={"principal": 100000, "annual_rate_pct": 12, "tenure_months": 24},
        )
        assert float(resp.json()["emi"]) > 0

    async def test_amortization_has_3_entries(self, client: AsyncClient):
        """first_3_months has exactly 3 amortization entries."""
        resp = await client.post(
            "/api/v1/calculator/loan-emi",
            json={"principal": 100000, "annual_rate_pct": 10, "tenure_months": 12},
        )
        assert resp.status_code == 200
        schedule = resp.json()["first_3_months"]
        assert len(schedule) == 3

    async def test_zero_tenure_fails(self, client: AsyncClient):
        """0 months tenure → 422."""
        resp = await client.post(
            "/api/v1/calculator/loan-emi",
            json={"principal": 10000, "annual_rate_pct": 10, "tenure_months": 0},
        )
        assert resp.status_code == 422

    async def test_negative_principal_fails(self, client: AsyncClient):
        """Negative principal → 422."""
        resp = await client.post(
            "/api/v1/calculator/loan-emi",
            json={"principal": -50000, "annual_rate_pct": 8, "tenure_months": 36},
        )
        assert resp.status_code == 422


# =============================================================================
# SIP ENDPOINT
# =============================================================================


class TestSIPEndpoint:
    """Tests for POST /api/v1/calculator/sip."""

    async def test_basic_request_succeeds(self, client: AsyncClient):
        """Valid SIP request returns 200 with expected keys."""
        resp = await client.post(
            "/api/v1/calculator/sip",
            json={
                "monthly_investment": 1000,
                "annual_rate_pct": 12,
                "years": 10,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "future_value" in data
        assert "total_invested" in data
        assert "wealth_gained" in data

    async def test_future_value_exceeds_invested(self, client: AsyncClient):
        """For positive rate, future value > total invested."""
        resp = await client.post(
            "/api/v1/calculator/sip",
            json={"monthly_investment": 1000, "annual_rate_pct": 10, "years": 15},
        )
        data = resp.json()
        assert float(data["future_value"]) > float(data["total_invested"])

    async def test_zero_years_fails(self, client: AsyncClient):
        """Zero years → 422."""
        resp = await client.post(
            "/api/v1/calculator/sip",
            json={"monthly_investment": 500, "annual_rate_pct": 12, "years": 0},
        )
        assert resp.status_code == 422


# =============================================================================
# SAVINGS PROJECTION ENDPOINT
# =============================================================================


class TestSavingsProjectionEndpoint:
    """Tests for POST /api/v1/calculator/savings-projection."""

    async def test_basic_request_succeeds(self, client: AsyncClient):
        """Valid savings projection returns 200."""
        resp = await client.post(
            "/api/v1/calculator/savings-projection",
            json={
                "current_savings": 10000,
                "monthly_contribution": 500,
                "annual_return_pct": 7,
                "years": 10,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "nominal_future_value" in data
        assert "real_future_value" in data
        assert "inflation_erosion" in data

    async def test_custom_inflation_rate(self, client: AsyncClient):
        """Custom inflation rate is accepted and used."""
        resp = await client.post(
            "/api/v1/calculator/savings-projection",
            json={
                "current_savings": 5000,
                "monthly_contribution": 200,
                "annual_return_pct": 8,
                "years": 5,
                "annual_inflation_pct": 5.0,
            },
        )
        assert resp.status_code == 200


# =============================================================================
# TAX ESTIMATE ENDPOINT
# =============================================================================


class TestTaxEstimateEndpoint:
    """Tests for POST /api/v1/calculator/tax-estimate."""

    async def test_basic_request_succeeds(self, client: AsyncClient):
        """Valid tax estimate returns 200 with expected keys."""
        resp = await client.post(
            "/api/v1/calculator/tax-estimate",
            json={"gross_income": 100000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_tax" in data
        assert "effective_rate_pct" in data
        assert "take_home" in data
        assert "bracket_breakdown" in data

    async def test_low_income_no_tax(self, client: AsyncClient):
        """Income below standard deduction ($14,600) → zero tax."""
        resp = await client.post(
            "/api/v1/calculator/tax-estimate",
            json={"gross_income": 10000},
        )
        assert resp.status_code == 200
        assert float(resp.json()["total_tax"]) == 0.0

    async def test_with_additional_deductions(self, client: AsyncClient):
        """Additional deductions are accepted."""
        resp = await client.post(
            "/api/v1/calculator/tax-estimate",
            json={"gross_income": 80000, "additional_deductions": 5000},
        )
        assert resp.status_code == 200

    async def test_negative_income_fails(self, client: AsyncClient):
        """Negative income → 422."""
        resp = await client.post(
            "/api/v1/calculator/tax-estimate",
            json={"gross_income": -10000},
        )
        assert resp.status_code == 422


# =============================================================================
# BUDGET PLANNER ENDPOINT
# =============================================================================


class TestBudgetPlannerEndpoint:
    """Tests for POST /api/v1/calculator/budget-planner."""

    async def test_basic_request_succeeds(self, client: AsyncClient):
        """Valid budget planner request returns 200."""
        resp = await client.post(
            "/api/v1/calculator/budget-planner",
            json={"monthly_income": 5000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "needs_50pct" in data
        assert "wants_30pct" in data
        assert "savings_20pct" in data

    async def test_50_30_20_values(self, client: AsyncClient):
        """$5000 income: needs=$2500, wants=$1500, savings=$1000."""
        resp = await client.post(
            "/api/v1/calculator/budget-planner",
            json={"monthly_income": 5000},
        )
        data = resp.json()
        assert float(data["needs_50pct"]) == 2500.0
        assert float(data["wants_30pct"]) == 1500.0
        assert float(data["savings_20pct"]) == 1000.0

    async def test_zero_income_fails(self, client: AsyncClient):
        """Zero income → 422 (must be positive)."""
        resp = await client.post(
            "/api/v1/calculator/budget-planner",
            json={"monthly_income": 0},
        )
        assert resp.status_code == 422

    async def test_returns_category_lists(self, client: AsyncClient):
        """Response includes helpful category lists."""
        resp = await client.post(
            "/api/v1/calculator/budget-planner",
            json={"monthly_income": 3000},
        )
        data = resp.json()
        assert isinstance(data["needs_categories"], list)
        assert len(data["needs_categories"]) > 0
