"""
Finance Calculator Router
===========================
HTTP endpoints for financial calculations.

All endpoints are POST (not GET) because:
  - Calculations take input parameters (request body is cleaner than long query strings)
  - No side effects (idempotent, but POST is conventional for "do something with data")
  - Request bodies support complex nested objects (amortization schedules, etc.)

These are PUBLIC endpoints (no auth required).
Why no auth? Calculators don't touch user data — anyone should be able to
use a compound interest calculator without signing up.

In production, you might rate-limit these to prevent abuse.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.calculator.service import (
    budget_planner,
    compound_interest,
    loan_emi,
    savings_projection,
    sip_calculator,
    tax_estimate,
)

router = APIRouter()


# =============================================================================
# REQUEST / RESPONSE SCHEMAS (inline — calculator schemas are simple enough)
# =============================================================================


class CompoundInterestRequest(BaseModel):
    principal: Decimal = Field(..., gt=0, examples=[Decimal("10000")])
    annual_rate_pct: Decimal = Field(..., gt=0, le=100, examples=[Decimal("8")])
    years: int = Field(..., ge=1, le=50, examples=[10])
    compounds_per_year: int = Field(default=12, ge=1, le=365)


class LoanEMIRequest(BaseModel):
    principal: Decimal = Field(..., gt=0, examples=[Decimal("500000")])
    annual_rate_pct: Decimal = Field(..., gt=0, le=100, examples=[Decimal("8.5")])
    tenure_months: int = Field(..., ge=1, le=360, examples=[240])


class SIPRequest(BaseModel):
    monthly_investment: Decimal = Field(..., gt=0, examples=[Decimal("500")])
    annual_rate_pct: Decimal = Field(..., gt=0, le=100, examples=[Decimal("12")])
    years: int = Field(..., ge=1, le=50, examples=[20])


class SavingsProjectionRequest(BaseModel):
    current_savings: Decimal = Field(
        default=Decimal("0"), ge=0, examples=[Decimal("5000")]
    )
    monthly_contribution: Decimal = Field(..., gt=0, examples=[Decimal("500")])
    annual_return_pct: Decimal = Field(..., gt=0, le=100, examples=[Decimal("7")])
    years: int = Field(..., ge=1, le=50, examples=[30])
    annual_inflation_pct: Decimal = Field(default=Decimal("3.0"), ge=0, le=20)


class TaxEstimateRequest(BaseModel):
    gross_income: Decimal = Field(..., gt=0, examples=[Decimal("100000")])
    filing_status: str = Field(default="single", examples=["single"])
    additional_deductions: Decimal = Field(default=Decimal("0"), ge=0)


class BudgetPlannerRequest(BaseModel):
    monthly_income: Decimal = Field(..., gt=0, examples=[Decimal("5000")])


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.post(
    "/compound-interest",
    summary="Calculate compound interest",
    description="""
Calculate how an investment grows with compound interest.

**Formula:** A = P × (1 + r/n)^(n×t)

**Example:** $10,000 at 8%/year compounded monthly for 10 years → $22,196.40
    """,
)
async def calc_compound_interest(data: CompoundInterestRequest) -> dict:
    return compound_interest(
        principal=data.principal,
        annual_rate_pct=data.annual_rate_pct,
        years=data.years,
        compounds_per_year=data.compounds_per_year,
    )


@router.post(
    "/loan-emi",
    summary="Calculate loan EMI",
    description="""
Calculate Equated Monthly Installment for a loan.

**Formula:** EMI = P × r(1+r)^n / ((1+r)^n - 1)

Also returns total interest paid and first 3 months amortization schedule.
    """,
)
async def calc_loan_emi(data: LoanEMIRequest) -> dict:
    return loan_emi(
        principal=data.principal,
        annual_rate_pct=data.annual_rate_pct,
        tenure_months=data.tenure_months,
    )


@router.post(
    "/sip",
    summary="Calculate SIP returns",
    description="""
Calculate returns on a Systematic Investment Plan (recurring monthly investment).

**Formula:** FV = P × ((1+r)^n - 1) / r × (1+r)

Useful for: mutual fund investments, recurring stock purchases.
    """,
)
async def calc_sip(data: SIPRequest) -> dict:
    return sip_calculator(
        monthly_investment=data.monthly_investment,
        annual_rate_pct=data.annual_rate_pct,
        years=data.years,
    )


@router.post(
    "/savings-projection",
    summary="Project savings growth",
    description="""
Project how savings grow over time with contributions and returns.

Returns both **nominal** (future dollars) and **real** (today's dollars, inflation-adjusted) values.
    """,
)
async def calc_savings_projection(data: SavingsProjectionRequest) -> dict:
    return savings_projection(
        current_savings=data.current_savings,
        monthly_contribution=data.monthly_contribution,
        annual_return_pct=data.annual_return_pct,
        years=data.years,
        annual_inflation_pct=data.annual_inflation_pct,
    )


@router.post(
    "/tax-estimate",
    summary="Estimate US federal income tax",
    description="""
Estimate US federal income tax using 2024 progressive tax brackets.

Returns effective rate, marginal rate, total tax, and bracket-by-bracket breakdown.

**Note:** This is an estimate for educational purposes. Consult a tax professional for actual filing.
    """,
)
async def calc_tax_estimate(data: TaxEstimateRequest) -> dict:
    return tax_estimate(
        gross_income=data.gross_income,
        filing_status=data.filing_status,
        additional_deductions=data.additional_deductions,
    )


@router.post(
    "/budget-planner",
    summary="Apply the 50/30/20 budget rule",
    description="""
Split your monthly income using the 50/30/20 rule:
- **50%** → Needs (rent, food, utilities)
- **30%** → Wants (dining, entertainment)
- **20%** → Savings & investments
    """,
)
async def calc_budget_planner(data: BudgetPlannerRequest) -> dict:
    return budget_planner(monthly_income=data.monthly_income)
