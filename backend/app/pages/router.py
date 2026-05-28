"""
HTML Page Routes
=================
Server-side rendered pages using Jinja2 templates.

Architecture: Two auth layers
  API routes (/api/v1/*) → Bearer JWT in Authorization header
  Page routes (/*, /dashboard, etc.) → JWT in httpOnly cookie

Why cookie auth for HTML pages?
  localStorage JWT → vulnerable to XSS (malicious scripts can steal it)
  httpOnly cookie → JS cannot access it at all (XSS protection)

  For API-first (mobile/SPA): Bearer JWT in header
  For server-rendered HTML: httpOnly cookie

Cookie flow:
  1. User submits /login form → POST /web/login
  2. Server validates credentials → AuthService.login_user()
  3. Server sets access_token as httpOnly cookie
  4. All subsequent page requests → cookie sent automatically by browser
  5. Server reads cookie, validates JWT, renders page with user data
  6. POST /web/logout → clears cookie → redirect to /login

HTMX pattern for dynamic content:
  Initial page load → full HTML (Jinja2 template)
  HTMX requests → HTML fragments (partial templates)
  This gives React-like interactivity without a JS framework.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import LoginRequest
from app.auth.service import AuthService
from app.core.security import verify_access_token
from app.database import get_db
from app.exceptions import InvalidCredentialsError

logger = structlog.get_logger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# =============================================================================
# DEPENDENCY: Read user from cookie (for protected pages)
# =============================================================================


async def get_user_from_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Dependency that reads the JWT access token from the httpOnly cookie.

    Returns the User ORM object if authenticated, None otherwise.
    Pages that require auth redirect to /login if this returns None.

    Why not raise an exception?
      Unlike API endpoints, HTML pages don't return JSON errors.
      They redirect to the login page instead.
    """
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = verify_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        auth_service = AuthService(db)
        return await auth_service.get_user_by_id(user_id)
    except Exception:
        return None


def _require_auth(request: Request, user):
    """Helper: redirect to login if not authenticated."""
    if not user:
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    return None


# =============================================================================
# PUBLIC PAGES
# =============================================================================


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user=Depends(get_user_from_cookie),
):
    """Root: redirect to dashboard if logged in, else to login."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user=Depends(get_user_from_cookie),
    next: str = "/dashboard",
    error: str = "",
):
    """Login page. Redirects to dashboard if already logged in."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"next": next, "error": error},
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    user=Depends(get_user_from_cookie),
    error: str = "",
):
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={"error": error},
    )


# =============================================================================
# WEB AUTH ACTIONS (form submissions)
# =============================================================================


@router.post("/web/login")
async def web_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/dashboard"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle login form submission.

    On success: set JWT in httpOnly cookie → redirect to dashboard
    On failure: redirect back to login page with error message

    Why redirect-after-POST (PRG pattern)?
      If we render the form on POST, browser shows "resubmit on refresh" warning.
      Redirect to GET after POST → no resubmit warning, bookmarkable.
    """
    try:
        service = AuthService(db)
        _, token_response = await service.login_user(
            LoginRequest(email=email, password=password)  # type: ignore[arg-type]
        )
        response = RedirectResponse(url=next, status_code=302)
        # httpOnly=True: JavaScript cannot read this cookie (XSS protection)
        # secure=True in production (HTTPS only) — set based on env
        response.set_cookie(
            key="access_token",
            value=token_response.access_token,
            httponly=True,
            max_age=token_response.expires_in,
            samesite="lax",
        )
        response.set_cookie(
            key="refresh_token",
            value=token_response.refresh_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,  # 7 days
            samesite="lax",
        )
        return response
    except InvalidCredentialsError:
        return RedirectResponse(
            url=f"/login?error=Invalid+email+or+password&next={next}",
            status_code=302,
        )
    except Exception:
        return RedirectResponse(
            url="/login?error=Something+went+wrong.+Please+try+again.",
            status_code=302,
        )


@router.post("/web/register")
async def web_register(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle register form submission."""
    from app.auth.schemas import RegisterRequest

    try:
        service = AuthService(db)
        await service.register_user(
            RegisterRequest(email=email, username=username, password=password)  # type: ignore[arg-type]
        )
        return RedirectResponse(
            url="/login?success=Account+created!+Please+log+in.", status_code=302
        )
    except Exception as e:
        error_msg = str(e).replace('"', "").replace("'", "")[:100]
        return RedirectResponse(url=f"/register?error={error_msg}", status_code=302)


@router.get("/web/logout")
async def web_logout(request: Request):
    """Clear auth cookies and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response


# =============================================================================
# PROTECTED PAGES
# =============================================================================


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
):
    """
    Main dashboard page.

    Fetches analytics data server-side (no extra API round-trip needed).
    Template receives pre-computed data — no JavaScript fetch required for initial load.
    HTMX handles dynamic updates after page load.
    """
    redirect = _require_auth(request, user)
    if redirect:
        return redirect

    from app.analytics.service import AnalyticsService

    now = datetime.now(UTC)
    year, month = now.year, now.month

    svc = AnalyticsService(db)

    # Fetch all dashboard data in parallel would be ideal; here sequential for clarity
    summary = await svc.get_dashboard_summary(user.id, year, month)
    categories = await svc.get_category_breakdown(user.id, year, month)
    top_expenses = await svc.get_top_expenses(user.id, year, month, limit=5)
    trends = await svc.get_monthly_trends(user.id, months=6)

    # Prepare chart data as JSON-serializable dicts
    category_chart = {
        "labels": [c["category_name"] for c in categories],
        "data": [float(c["total"]) for c in categories],
        "colors": [c["color"] for c in categories],
    }
    trend_chart = {
        "labels": [t["month_label"] for t in trends],
        "expenses": [float(t["total_expenses"]) for t in trends],
        "income": [float(t["total_income"]) for t in trends],
    }

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "user": user,
            "summary": summary,
            "categories": categories,
            "top_expenses": top_expenses,
            "trends": trends,
            "category_chart": category_chart,
            "trend_chart": trend_chart,
            "current_month": now.strftime("%B %Y"),
        },
    )


@router.get("/expenses", response_class=HTMLResponse)
async def expenses_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
    search: str = "",
    page_cursor: str = "",
):
    """Expenses list page with HTMX-powered filtering and pagination."""
    redirect = _require_auth(request, user)
    if redirect:
        return redirect

    from app.expenses.schemas import ExpenseFilters
    from app.expenses.service import CategoryService, ExpenseService

    cat_svc = CategoryService(db)
    exp_svc = ExpenseService(db)

    categories = await cat_svc.list_categories(user.id)
    filters = ExpenseFilters(
        search=search or None, cursor=page_cursor or None, limit=10
    )
    expenses_page_data = await exp_svc.list_expenses(user.id, filters)

    return templates.TemplateResponse(
        request=request,
        name="expenses/list.html",
        context={
            "user": user,
            "expenses": expenses_page_data,
            "categories": categories,
            "search": search,
        },
    )


# =============================================================================
# WEB EXPENSE ACTIONS (form → server → HTMX response)
# =============================================================================
# These routes exist so HTMX forms can submit as multipart/form-data
# and get back HTML fragments to swap into the page.
#
# Why not POST directly to /api/v1/expenses?
#   The API expects JSON. HTML forms submit application/x-www-form-urlencoded.
#   Rather than forcing HTMX to serialize JSON, these web routes accept form
#   data, call the same service layer, and return HTML fragments.
# =============================================================================


@router.post("/web/expenses/create", response_class=HTMLResponse)
async def web_create_expense(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
    amount: str = Form(...),
    description: str = Form(...),
    category_id: str = Form(default=""),
    date: str = Form(default=""),
    notes: str = Form(default=""),
):
    """
    Handle Add Expense form submission from the expenses page.
    Returns an HTMX HTML fragment (the new table row) on success,
    or an error message fragment on failure.
    """
    if not user:
        return HTMLResponse(
            '<div class="text-red-600 text-sm p-3">Session expired. Please <a href="/login" class="underline">log in</a>.</div>',
            status_code=401,
        )

    from decimal import Decimal, InvalidOperation

    from app.expenses.schemas import ExpenseCreate
    from app.expenses.service import ExpenseService

    try:
        amount_decimal = Decimal(amount)
        if amount_decimal <= 0:
            raise ValueError("Amount must be positive")
    except (InvalidOperation, ValueError):
        return HTMLResponse(
            '<div class="text-red-600 text-sm p-3 bg-red-50 rounded-lg">❌ Invalid amount. Please enter a positive number.</div>'
        )

    try:
        svc = ExpenseService(db)
        create_kwargs: dict = {
            "amount": amount_decimal,
            "description": description.strip(),
            "category_id": category_id if category_id else None,
            "notes": notes.strip() if notes else None,
        }
        # Only pass date if the form provided one — otherwise ExpenseCreate defaults to now()
        if date:
            from datetime import datetime as dt

            create_kwargs["date"] = dt.fromisoformat(date)

        expense = await svc.create_expense(
            user_id=user.id,
            data=ExpenseCreate(**create_kwargs),
        )

        # Return a success banner + trigger a full table refresh via HTMX event
        return HTMLResponse(
            f"""
<div id="add-expense-feedback"
     class="p-3 bg-green-50 border border-green-200 text-green-800 text-sm rounded-lg flex items-center justify-between"
     hx-trigger="load delay:3s"
     hx-swap-oob="true">
  <span>✅ Added <strong>${float(expense.amount):.2f}</strong> — {expense.description}</span>
  <button onclick="document.getElementById('add-expense-feedback').remove()" class="text-green-600 hover:text-green-800 font-bold ml-2">×</button>
</div>
<div hx-get="/web/expenses-table"
     hx-trigger="load"
     hx-target="#expenses-table-container"
     hx-swap="innerHTML">
</div>
"""
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-red-600 text-sm p-3 bg-red-50 rounded-lg">❌ {str(e)[:120]}</div>'
        )


@router.get("/web/expenses-table", response_class=HTMLResponse)
async def web_expenses_table(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
    search: str = "",
    page_cursor: str = "",
):
    """Returns just the expenses table HTML fragment (for HTMX partial refresh)."""
    if not user:
        return HTMLResponse("")

    from app.expenses.schemas import ExpenseFilters
    from app.expenses.service import ExpenseService

    svc = ExpenseService(db)
    filters = ExpenseFilters(
        search=search or None, cursor=page_cursor or None, limit=10
    )
    expenses_data = await svc.list_expenses(user.id, filters)

    return templates.TemplateResponse(
        request=request,
        name="expenses/table_fragment.html",
        context={"expenses": expenses_data, "search": search, "user": user},
    )


@router.get("/calculator", response_class=HTMLResponse)
async def calculator_page(
    request: Request,
    user=Depends(get_user_from_cookie),
):
    """Finance calculators page — compound interest, EMI, SIP, tax, savings, budget planner."""
    redirect = _require_auth(request, user)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="calculator/index.html",
        context={"user": user},
    )


# =============================================================================
# CSV IMPORT WEB ROUTES
# =============================================================================


@router.get("/import", response_class=HTMLResponse)
async def import_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
):
    """CSV / PDF import landing page — shows upload form with format guide."""
    redirect = _require_auth(request, user)
    if redirect:
        return redirect

    from app.expenses.service import CategoryService

    cat_svc = CategoryService(db)
    categories = await cat_svc.list_categories(user.id)

    return templates.TemplateResponse(
        request=request,
        name="expenses/import.html",
        context={"user": user, "categories": categories},
    )


@router.post("/web/expenses/import/preview", response_class=HTMLResponse)
async def web_import_preview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
):
    """
    Accept uploaded CSV, PDF, or Excel file, parse it, return an HTML preview table.

    Supports:
      - CSV:  PhonePe, GPay, Paytm, HDFC, SBI, Generic
      - PDF:  HDFC, SBI, Paytm Bank, Paytm UPI Statement, Generic bank statements
      - XLSX: Any bank with Date, Description, Debit/Credit columns

    Uses request.form() directly because UploadFile + HTMX multipart
    needs manual form body reading.
    """
    if not user:
        return HTMLResponse(
            '<div class="text-red-600 p-4">Session expired. Please log in.</div>',
            status_code=401,
        )

    from app.expenses.import_service import parse_file
    from app.expenses.service import CategoryService

    try:
        form = await request.form()
        file_field = form.get("csv_file")
        if not file_field or not hasattr(file_field, "read"):
            return HTMLResponse(
                '<div class="text-red-600 p-4">❌ Please select a CSV, PDF, or Excel (.xlsx) file.</div>'
            )

        filename = getattr(file_field, "filename", "upload.csv") or "upload.csv"
        content = await file_field.read()
        if not content:
            return HTMLResponse(
                '<div class="text-red-600 p-4">❌ The file is empty.</div>'
            )

        cat_svc = CategoryService(db)
        categories = await cat_svc.list_categories(user.id)
        user_cats = [
            {"id": str(c.id), "name": c.name, "icon": c.icon} for c in categories
        ]

        preview = parse_file(content, filename, user_cats)

        if not preview.transactions:
            return HTMLResponse(
                '<div class="text-yellow-700 bg-yellow-50 border border-yellow-200 rounded-xl p-4">'
                "⚠️ No transactions could be parsed from this file. "
                "<br>Please make sure it is a valid statement export (CSV, PDF, or Excel) from PhonePe, GPay, Paytm, HDFC, or SBI.</div>"
            )

        return templates.TemplateResponse(
            request=request,
            name="expenses/import_preview.html",
            context={
                "user": user,
                "preview": preview,
                "categories": categories,
            },
        )
    except Exception as e:
        logger.error("import_preview_error", error=str(e))
        return HTMLResponse(
            f'<div class="text-red-600 bg-red-50 border border-red-200 rounded-xl p-4">❌ Error parsing file: {str(e)[:300]}</div>'
        )


@router.post("/web/expenses/import/confirm", response_class=HTMLResponse)
async def web_import_confirm(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
):
    """
    Bulk-create selected expenses from the preview.

    Duplicate detection:
      Before creating each expense, we query the database for an existing
      active expense with the same (user_id, date, amount, description).
      If found → skip and count as duplicate.

      Additionally, if the transaction has a UPI Ref No., we store it in the
      expense's `notes` field as "UPI Ref: <ref>" so future imports can also
      match by reference.

    Returns a rich HTML summary: imported / duplicates / errors.
    """
    if not user:
        return HTMLResponse(
            '<div class="text-red-600 p-4">Session expired.</div>', status_code=401
        )

    import json
    from datetime import datetime as dt
    from decimal import Decimal

    from sqlalchemy import func, select

    from app.expenses.models import Expense
    from app.expenses.schemas import ExpenseCreate
    from app.expenses.service import ExpenseService

    try:
        body = await request.body()
        data = json.loads(body)
        transactions = data.get("transactions", [])

        if not transactions:
            return HTMLResponse(
                '<div class="text-yellow-700 p-4">⚠️ No transactions selected.</div>'
            )

        svc = ExpenseService(db)
        created = 0
        duplicates = 0
        errors = 0

        for tx in transactions:
            try:
                tx_amount = Decimal(str(tx["amount"]))
                tx_desc = (tx.get("description") or "")[:200]
                tx_ref = (tx.get("reference") or "").strip()

                # ── Parse date ───────────────────────────────────────────
                if tx.get("date"):
                    tx_dt = dt.fromisoformat(tx["date"])
                else:
                    tx_dt = dt.now()

                tx_date_only = tx_dt.date()

                # ── Duplicate check 1: by UPI Ref No. ────────────────────
                # UPI refs are globally unique — the fastest, most reliable check.
                if tx_ref:
                    upi_note = f"UPI Ref: {tx_ref}"
                    ref_result = await db.execute(
                        select(Expense)
                        .where(
                            Expense.user_id == user.id,
                            Expense.deleted_at.is_(None),
                            Expense.notes == upi_note,
                        )
                        .limit(1)
                    )
                    if ref_result.scalar_one_or_none():
                        duplicates += 1
                        continue

                # ── Duplicate check 2: by date + amount + description ────
                # Catches re-uploads without UPI refs (CSV / generic formats).
                date_result = await db.execute(
                    select(Expense)
                    .where(
                        Expense.user_id == user.id,
                        Expense.deleted_at.is_(None),
                        func.date(Expense.date) == tx_date_only,
                        Expense.amount == tx_amount,
                        Expense.description == tx_desc,
                    )
                    .limit(1)
                )
                if date_result.scalar_one_or_none():
                    duplicates += 1
                    continue

                # ── Create expense ───────────────────────────────────────
                notes_val = (
                    f"UPI Ref: {tx_ref}" if tx_ref else (tx.get("reference") or None)
                )

                create_data = ExpenseCreate(
                    amount=tx_amount,
                    description=tx_desc,
                    category_id=tx.get("category_id") or None,
                    notes=notes_val,
                    date=tx_dt,
                )
                await svc.create_expense(user_id=user.id, data=create_data)
                created += 1

            except Exception as e:
                logger.warning("import_confirm_row_error", error=str(e))
                errors += 1

        # ── Build response HTML ──────────────────────────────────────────
        parts = []
        if created:
            parts.append(
                f'<span class="text-green-800">✅ Imported <strong>{created}</strong>'
                f' expense{"s" if created != 1 else ""}.</span>'
            )
        if duplicates:
            parts.append(
                f'<span class="text-amber-700">⚠️ Skipped <strong>{duplicates}</strong>'
                f' duplicate{"s" if duplicates != 1 else ""} (already in your records).</span>'
            )
        if errors:
            parts.append(
                f'<span class="text-red-700">❌ <strong>{errors}</strong>'
                f' row{"s" if errors != 1 else ""} failed due to errors.</span>'
            )
        if not parts:
            parts.append('<span class="text-gray-700">Nothing was imported.</span>')

        summary_html = " &nbsp;·&nbsp; ".join(parts)

        return HTMLResponse(
            f"""
<div class="p-4 bg-green-50 border border-green-200 rounded-xl text-sm space-y-2">
  <div>{summary_html}</div>
  {'<p class="text-xs text-amber-700 mt-1">Duplicates are detected by UPI Ref No. or matching date + amount + description.</p>' if duplicates else ''}
  <div class="mt-3">
    <a href="/expenses" class="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold transition-colors">
      View Expenses →
    </a>
  </div>
</div>
"""
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-red-600 bg-red-50 border border-red-200 rounded-xl p-4">❌ Import failed: {str(e)[:200]}</div>'
        )


@router.delete("/web/expenses/{expense_id}", response_class=HTMLResponse)
async def web_delete_expense(
    expense_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_user_from_cookie),
):
    """Delete an expense and return empty string (HTMX removes the row)."""
    if not user:
        return HTMLResponse("", status_code=401)

    import uuid

    from app.expenses.service import ExpenseService

    try:
        svc = ExpenseService(db)
        await svc.delete_expense(expense_id=uuid.UUID(expense_id), user_id=user.id)
        # Return empty — HTMX swaps outerHTML with nothing, removing the row
        return HTMLResponse("")
    except Exception:
        return HTMLResponse(
            '<td colspan="5" class="px-6 py-3 text-red-500 text-sm">Failed to delete — try again</td>'
        )
