"""
Finance Calculator — Pure Business Logic
==========================================
Stateless calculation functions. No database, no auth — pure math.

Why use Decimal instead of float?
  float(0.1) + float(0.2) = 0.30000000000000004   ← WRONG!
  Decimal("0.1") + Decimal("0.2") = Decimal("0.3") ← CORRECT

  IEEE 754 floating-point can't represent 0.1 exactly in binary.
  For financial calculations, even a tiny error compounds over time:
  $10,000 × 5% compounded daily for 10 years → float gives wrong cents.

  Rule: ALWAYS use decimal.Decimal for money math. Never float.

getcontext().prec = 28 gives us 28 significant digits — enough for any
realistic financial calculation without losing precision.

Formulas implemented:
  1. Compound Interest:  A = P(1 + r/n)^(nt)
  2. Loan EMI:           EMI = P × r(1+r)^n / ((1+r)^n - 1)
  3. SIP (monthly):      FV = P × ((1+r)^n - 1) / r × (1+r)
  4. Savings projection: FV with optional inflation adjustment
  5. Tax estimation:     Bracket-based progressive tax
  6. 50/30/20 rule:      Budget split recommendation

Interview: "We use Python's decimal.Decimal for all financial math —
float has binary representation errors that compound in calculations.
All calculators are pure functions (no side effects, no DB) — easy to
test, easy to reason about."
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, getcontext

# Set precision high enough for financial calculations
# 28 digits gives us room for large numbers with many decimal places
getcontext().prec = 28

# Convenience: round to 2 decimal places (cents)
CENTS = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    """Round to 2 decimal places using standard financial rounding (half-up)."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


# =============================================================================
# 1. COMPOUND INTEREST  →  A = P(1 + r/n)^(nt)
# =============================================================================


def compound_interest(
    principal: Decimal,
    annual_rate_pct: Decimal,
    years: int,
    compounds_per_year: int = 12,
) -> dict[str, object]:
    """
    Calculate compound interest.

    Formula: A = P × (1 + r/n)^(n×t)
      P = principal (initial amount)
      r = annual interest rate (as decimal, e.g., 0.08 for 8%)
      n = compounds per year (12=monthly, 4=quarterly, 1=annually)
      t = time in years

    Returns: principal, total_amount, interest_earned, effective_annual_rate

    Why compound interest beats simple interest:
      Simple: $1000 × 8% × 10 years = $800 interest
      Compound (monthly): $1000 at 8%/year compounded monthly = $2219.64 total
      Extra $419.64 — the "interest on interest" effect.

    The Rule of 72: Years to double = 72 / interest_rate
      At 8%: 72/8 = 9 years to double your money.
    """
    r = annual_rate_pct / Decimal("100")
    n = Decimal(str(compounds_per_year))
    t = Decimal(str(years))

    # A = P × (1 + r/n)^(n×t)
    total = principal * (1 + r / n) ** (n * t)
    interest_earned = total - principal

    # Effective Annual Rate: actual annual yield accounting for compounding
    # EAR = (1 + r/n)^n - 1
    ear = (1 + r / n) ** n - 1

    return {
        "principal": _round(principal),
        "total_amount": _round(total),
        "interest_earned": _round(interest_earned),
        "annual_rate_pct": _round(annual_rate_pct),
        "effective_annual_rate_pct": _round(ear * 100),
        "years": years,
        "compounds_per_year": compounds_per_year,
    }


# =============================================================================
# 2. LOAN EMI  →  EMI = P × r(1+r)^n / ((1+r)^n - 1)
# =============================================================================


def loan_emi(
    principal: Decimal,
    annual_rate_pct: Decimal,
    tenure_months: int,
) -> dict[str, object]:
    """
    Calculate Equated Monthly Installment (loan payment).

    Formula: EMI = P × r × (1+r)^n / ((1+r)^n - 1)
      P = loan amount
      r = monthly interest rate = annual_rate / 12 / 100
      n = total number of monthly payments

    Returns: emi, total_payment, total_interest, amortization schedule (first/last 3)

    This formula is used for: home loans, car loans, personal loans.
    Every bank uses this exact formula.

    Example: $10,000 at 12% for 24 months
      r = 12/12/100 = 0.01
      EMI = 10000 × 0.01 × (1.01)^24 / ((1.01)^24 - 1) = $470.73
    """
    r = annual_rate_pct / Decimal("100") / Decimal("12")  # Monthly rate
    n = Decimal(str(tenure_months))

    if r == 0:
        # 0% interest — simple division
        emi = principal / n
    else:
        # EMI formula
        emi = principal * r * (1 + r) ** n / ((1 + r) ** n - 1)

    total_payment = emi * n
    total_interest = total_payment - principal

    # Amortization: break down first 3 months
    schedule = []
    balance = principal
    for month in range(1, min(4, tenure_months + 1)):
        interest_part = balance * r
        principal_part = emi - interest_part
        balance -= principal_part
        schedule.append(
            {
                "month": month,
                "emi": _round(emi),
                "principal_part": _round(principal_part),
                "interest_part": _round(interest_part),
                "balance": _round(max(balance, Decimal("0"))),
            }
        )

    return {
        "principal": _round(principal),
        "annual_rate_pct": _round(annual_rate_pct),
        "tenure_months": tenure_months,
        "emi": _round(emi),
        "total_payment": _round(total_payment),
        "total_interest": _round(total_interest),
        "interest_to_principal_ratio": _round(total_interest / principal * 100),
        "first_3_months": schedule,
    }


# =============================================================================
# 3. SIP (Systematic Investment Plan)
# =============================================================================


def sip_calculator(
    monthly_investment: Decimal,
    annual_rate_pct: Decimal,
    years: int,
) -> dict[str, object]:
    """
    Calculate the future value of a Systematic Investment Plan (SIP).

    SIP = investing a fixed amount every month (like a recurring mutual fund).

    Formula (Future Value of annuity):
      FV = P × ((1 + r)^n - 1) / r × (1 + r)
      P = monthly investment
      r = monthly rate = annual_rate / 12 / 100
      n = total months = years × 12

    Why SIP beats lump sum (often):
      Rupee/Dollar Cost Averaging: you buy more units when prices are low,
      fewer when prices are high. Over time, this averages out market volatility.

    Example: $500/month at 12%/year for 20 years
      Total invested: $120,000
      Future value:   ~$494,000 (4× your investment!)
    """
    r = annual_rate_pct / Decimal("100") / Decimal("12")
    n = Decimal(str(years * 12))
    principal = monthly_investment

    if r == 0:
        future_value = principal * n
    else:
        future_value = principal * ((1 + r) ** n - 1) / r * (1 + r)

    total_invested = principal * n
    wealth_gained = future_value - total_invested

    return {
        "monthly_investment": _round(principal),
        "annual_rate_pct": _round(annual_rate_pct),
        "years": years,
        "total_invested": _round(total_invested),
        "future_value": _round(future_value),
        "wealth_gained": _round(wealth_gained),
        "return_on_investment_pct": _round(wealth_gained / total_invested * 100),
    }


# =============================================================================
# 4. SAVINGS PROJECTION (with optional inflation adjustment)
# =============================================================================


def savings_projection(
    current_savings: Decimal,
    monthly_contribution: Decimal,
    annual_return_pct: Decimal,
    years: int,
    annual_inflation_pct: Decimal = Decimal("3.0"),
) -> dict[str, object]:
    """
    Project savings growth over time, adjusted for inflation.

    Nominal value: what you'll have in future dollars
    Real value: what it's worth in today's dollars (inflation-adjusted)

    Real return rate ≈ nominal rate - inflation rate
    (More precisely: (1 + nominal) / (1 + inflation) - 1)

    This is crucial: $1M in 30 years at 3% inflation is worth only $411K today.
    Always plan with inflation-adjusted returns!
    """
    r = annual_return_pct / Decimal("100") / Decimal("12")  # Monthly return
    inf = annual_inflation_pct / Decimal("100")
    n_months = years * 12

    # Future value of current savings (lump sum compound)
    fv_savings = current_savings * (1 + r) ** Decimal(str(n_months))

    # Future value of monthly contributions (SIP formula)
    if r == 0:
        fv_contributions = monthly_contribution * Decimal(str(n_months))
    else:
        fv_contributions = (
            monthly_contribution * ((1 + r) ** Decimal(str(n_months)) - 1) / r * (1 + r)
        )

    nominal_value = fv_savings + fv_contributions
    total_contributed = monthly_contribution * Decimal(str(n_months))

    # Inflation adjustment: real value = nominal / (1 + inf)^years
    real_value = nominal_value / (1 + inf) ** Decimal(str(years))

    return {
        "current_savings": _round(current_savings),
        "monthly_contribution": _round(monthly_contribution),
        "annual_return_pct": _round(annual_return_pct),
        "annual_inflation_pct": _round(annual_inflation_pct),
        "years": years,
        "total_contributed": _round(total_contributed),
        "nominal_future_value": _round(nominal_value),
        "real_future_value": _round(real_value),
        "inflation_erosion": _round(nominal_value - real_value),
    }


# =============================================================================
# 5. TAX ESTIMATION (US Federal, simplified 2024 brackets)
# =============================================================================

# 2024 US Federal Tax Brackets (Single filer)
# Real brackets from IRS — good for interviews!
_TAX_BRACKETS_SINGLE = [
    (Decimal("11600"), Decimal("10")),  # 10% on first $11,600
    (Decimal("47150"), Decimal("12")),  # 12% on $11,601–$47,150
    (Decimal("100525"), Decimal("22")),  # 22% on $47,151–$100,525
    (Decimal("191950"), Decimal("24")),  # 24% on $100,526–$191,950
    (Decimal("243725"), Decimal("32")),  # 32% on $191,951–$243,725
    (Decimal("609350"), Decimal("35")),  # 35% on $243,726–$609,350
    (Decimal("999999999"), Decimal("37")),  # 37% on $609,351+
]

_STANDARD_DEDUCTION_SINGLE = Decimal("14600")  # 2024 standard deduction


def tax_estimate(
    gross_income: Decimal,
    filing_status: str = "single",
    additional_deductions: Decimal = Decimal("0"),
) -> dict[str, object]:
    """
    Estimate US federal income tax using progressive brackets.

    Progressive tax = different rates for different income bands.
    NOT all income taxed at the top rate (common misconception!).

    Example: $100,000 income (single, 2024):
      First $11,600 → 10% → $1,160
      $11,601–$47,150 → 12% → $4,266
      $47,151–$100,000 → 22% → $11,627
      Total: $17,053   ← NOT $100,000 × 22% = $22,000

    Effective rate = actual tax paid / gross income (always lower than marginal)
    Marginal rate = rate on the last dollar earned
    """
    standard_deduction = _STANDARD_DEDUCTION_SINGLE
    taxable_income = max(
        Decimal("0"), gross_income - standard_deduction - additional_deductions
    )

    total_tax = Decimal("0")
    breakdown = []
    prev_limit = Decimal("0")

    for limit, rate in _TAX_BRACKETS_SINGLE:
        if taxable_income <= prev_limit:
            break
        taxable_in_bracket = min(taxable_income, limit) - prev_limit
        tax_in_bracket = taxable_in_bracket * rate / Decimal("100")
        if taxable_in_bracket > 0:
            breakdown.append(
                {
                    "bracket_pct": float(rate),
                    "taxable_amount": _round(taxable_in_bracket),
                    "tax": _round(tax_in_bracket),
                }
            )
        total_tax += tax_in_bracket
        prev_limit = limit

    effective_rate = (
        total_tax / gross_income * 100 if gross_income > 0 else Decimal("0")
    )
    take_home = gross_income - total_tax

    return {
        "gross_income": _round(gross_income),
        "standard_deduction": _round(standard_deduction),
        "additional_deductions": _round(additional_deductions),
        "taxable_income": _round(taxable_income),
        "total_tax": _round(total_tax),
        "effective_rate_pct": _round(effective_rate),
        "take_home": _round(take_home),
        "bracket_breakdown": breakdown,
    }


# =============================================================================
# 6. 50/30/20 BUDGET RULE
# =============================================================================


def budget_planner(monthly_income: Decimal) -> dict[str, object]:
    """
    Apply the 50/30/20 rule to monthly income.

    50/30/20 Rule (Elizabeth Warren, "All Your Worth"):
      50% → Needs: rent, groceries, utilities, insurance, minimum debt payments
      30% → Wants: dining out, entertainment, hobbies, non-essential shopping
      20% → Savings & debt payoff: emergency fund, investments, extra debt

    This is the most widely recommended budgeting framework.
    Simple to understand, easy to track, works for most income levels.

    At what income does this break down?
      Very low income: 50% may not cover rent in high-cost cities → adjust to 60/20/20
      Very high income: 20% savings might be too low for wealth building → aim for 30%+
    """
    needs = monthly_income * Decimal("0.50")
    wants = monthly_income * Decimal("0.30")
    savings = monthly_income * Decimal("0.20")

    return {
        "monthly_income": _round(monthly_income),
        "needs_50pct": _round(needs),
        "wants_30pct": _round(wants),
        "savings_20pct": _round(savings),
        "needs_categories": [
            "Rent/Mortgage",
            "Groceries",
            "Utilities",
            "Insurance",
            "Minimum debt payments",
            "Transportation",
        ],
        "wants_categories": [
            "Dining out",
            "Entertainment",
            "Hobbies",
            "Clothing (non-essential)",
            "Subscriptions",
            "Travel",
        ],
        "savings_categories": [
            "Emergency fund (3-6 months expenses)",
            "Retirement (401k/IRA)",
            "Investment accounts",
            "Extra debt payoff",
        ],
    }
