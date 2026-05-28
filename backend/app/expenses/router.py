"""
Expense and Category HTTP Routers
===================================
Thin HTTP layer — parse request, call service, return response.

Two routers in one file:
  categories_router → /api/v1/categories
  expenses_router   → /api/v1/expenses

HTTP Status Codes used:
  200 OK           → successful GET, PUT, DELETE (when returning data)
  201 Created      → successful POST (resource was created)
  204 No Content   → successful DELETE (no body returned)
  400 Bad Request  → validation failed (FastAPI handles this via 422)
  401 Unauthorized → not authenticated
  403 Forbidden    → authenticated but not allowed
  404 Not Found    → resource doesn't exist
  409 Conflict     → duplicate resource (same name category)

Why 204 for DELETE?
  The resource was deleted — there's nothing to return.
  204 tells the client "it worked, don't expect a body."
  Some APIs return 200 with {"message": "deleted"} — either is acceptable,
  but 204 is more semantically correct per REST conventions.

Interview: "REST status codes carry semantic meaning. 201 signals creation,
204 signals successful deletion with no content. We use 404 for missing
resources and 403 when the resource exists but you don't own it. This gives
clients precise information to handle errors correctly."
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.core.pagination import Page
from app.dependencies import DB, CurrentUser
from app.expenses.models import CategoryType
from app.expenses.schemas import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    ExpenseCreate,
    ExpenseFilters,
    ExpenseResponse,
    ExpenseUpdate,
)
from app.expenses.service import CategoryService, ExpenseService

logger = structlog.get_logger(__name__)

# Two separate routers — registered independently in routers.py
categories_router = APIRouter()
expenses_router = APIRouter()


# =============================================================================
# CATEGORY ENDPOINTS
# =============================================================================


@categories_router.get(
    "",
    response_model=list[CategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List all accessible categories",
    description="""
Returns all categories visible to the current user:
- **System defaults** (Food, Transport, Salary, etc.) — visible to everyone
- **Your custom categories** — only visible to you

Optionally filter by type: `expense`, `income`, or `both`.
    """,
)
async def list_categories(
    current_user: CurrentUser,
    db: DB,
    category_type: CategoryType | None = Query(
        default=None,
        description="Filter by type: expense, income, or both",
    ),
) -> list[CategoryResponse]:
    """
    List categories (system defaults + user's own).

    Note: response_model=list[CategoryResponse] tells FastAPI to serialize
    a list of Category ORM objects using the CategoryResponse schema.
    FastAPI calls CategoryResponse.model_validate(obj) for each item.
    """
    service = CategoryService(db)
    categories = await service.list_categories(
        user_id=current_user.id,
        category_type=category_type,
    )
    return [CategoryResponse.from_orm(c) for c in categories]


@categories_router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom category",
)
async def create_category(
    data: CategoryCreate,
    current_user: CurrentUser,
    db: DB,
) -> CategoryResponse:
    service = CategoryService(db)
    category = await service.create_category(
        user_id=current_user.id,
        data=data,
    )
    return CategoryResponse.from_orm(category)


@categories_router.put(
    "/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a category",
    description="Update your own category. System defaults cannot be modified.",
)
async def update_category(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    current_user: CurrentUser,
    db: DB,
) -> CategoryResponse:
    service = CategoryService(db)
    category = await service.update_category(
        category_id=category_id,
        user_id=current_user.id,
        data=data,
    )
    return CategoryResponse.from_orm(category)


@categories_router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # Explicit None — prevents FastAPI inferring NoneType as response model
    summary="Delete a category",
    description="Soft-delete a category. System defaults cannot be deleted.",
)
async def delete_category(
    category_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
):
    """
    Why return None with 204?
      FastAPI maps None return + status_code=204 → HTTP 204 No Content.
      There's no body to serialize because the resource no longer exists.
    """
    service = CategoryService(db)
    await service.delete_category(
        category_id=category_id,
        user_id=current_user.id,
    )


# =============================================================================
# EXPENSE ENDPOINTS
# =============================================================================


@expenses_router.get(
    "",
    response_model=Page[ExpenseResponse],
    status_code=status.HTTP_200_OK,
    summary="List expenses with filtering and pagination",
    description="""
Returns a paginated list of your expenses.

**Filtering:**
- `from_date` / `to_date`: date range (ISO 8601 format)
- `category_id`: filter by category UUID
- `min_amount` / `max_amount`: amount range
- `search`: case-insensitive search in description
- `is_recurring`: filter recurring expenses

**Pagination:**
- Returns `limit` items (default 20, max 100)
- Response includes `next_cursor` if there are more pages
- Send `?cursor=<next_cursor>` for the next page
- When `has_next=false`, you've seen all results

**Example:**
```
GET /expenses?search=netflix&limit=10
→ { items: [...], has_next: true, next_cursor: "eyJk...", limit: 10 }

GET /expenses?search=netflix&limit=10&cursor=eyJk...
→ { items: [...], has_next: false, next_cursor: null, limit: 10 }
```
    """,
)
async def list_expenses(
    current_user: CurrentUser,
    db: DB,
    filters: ExpenseFilters = Depends(),
    # ↑ Depends() with no argument means "inject ExpenseFilters from query params"
    # FastAPI reads each ExpenseFilters field from the query string automatically.
    # This is equivalent to: from_date=Query(None), to_date=Query(None), etc.
    # but much cleaner when you have many filters.
) -> Page[ExpenseResponse]:
    """
    List expenses with cursor pagination and filters.

    Why filters: ExpenseFilters = Depends()?
      Without Depends: def list_expenses(from_date=None, to_date=None, search=None, ...)
      With Depends:    def list_expenses(filters: ExpenseFilters = Depends())

      Depends() tells FastAPI to construct ExpenseFilters from the query params.
      Pydantic validates each param (type, range, etc.) automatically.
      Much cleaner with 7+ filter parameters.
    """
    service = ExpenseService(db)
    return await service.list_expenses(
        user_id=current_user.id,
        filters=filters,
    )


@expenses_router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new expense",
)
async def create_expense(
    data: ExpenseCreate,
    current_user: CurrentUser,
    db: DB,
) -> ExpenseResponse:
    service = ExpenseService(db)
    expense = await service.create_expense(
        user_id=current_user.id,
        data=data,
    )
    return ExpenseResponse.model_validate(expense)


@expenses_router.get(
    "/{expense_id}",
    response_model=ExpenseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single expense",
)
async def get_expense(
    expense_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> ExpenseResponse:
    """
    Get a single expense by ID.

    Returns 404 if the expense doesn't exist OR doesn't belong to you.
    We intentionally don't return 403 here — that would reveal the expense exists.
    "Resource not found" is safer than "resource exists but you can't see it."
    """
    service = ExpenseService(db)
    expense = await service.get_expense(
        expense_id=expense_id,
        user_id=current_user.id,
    )
    return ExpenseResponse.model_validate(expense)


@expenses_router.put(
    "/{expense_id}",
    response_model=ExpenseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an expense",
    description="Partial update (PATCH semantics) — only send the fields you want to change.",
)
async def update_expense(
    expense_id: uuid.UUID,
    data: ExpenseUpdate,
    current_user: CurrentUser,
    db: DB,
) -> ExpenseResponse:
    service = ExpenseService(db)
    expense = await service.update_expense(
        expense_id=expense_id,
        user_id=current_user.id,
        data=data,
    )
    return ExpenseResponse.model_validate(expense)


@expenses_router.delete(
    "/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # Explicit None — prevents FastAPI inferring NoneType as response model
    summary="Delete an expense",
    description="Soft-delete an expense. The record is kept for audit purposes.",
)
async def delete_expense(
    expense_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
):
    service = ExpenseService(db)
    await service.delete_expense(
        expense_id=expense_id,
        user_id=current_user.id,
    )


# =============================================================================
# CSV IMPORT ENDPOINTS
# =============================================================================


@expenses_router.post(
    "/import/preview",
    status_code=status.HTTP_200_OK,
    summary="Preview CSV import",
    description="""
Upload a **CSV or PDF** export from PhonePe, Google Pay, Paytm, HDFC, or SBI.
Returns a preview of parsed transactions with suggested categories.
No expenses are created — call /import/confirm to actually save them.

Supported formats (CSV and PDF):
- **PhonePe**: Transaction history CSV from PhonePe app
- **Google Pay**: Activity export from myaccount.google.com
- **Paytm**: Passbook CSV / Paytm Bank statement PDF
- **HDFC**: Account statement CSV or PDF from HDFC NetBanking
- **SBI**: Account statement CSV or PDF from OnlineSBI
- **Generic**: Any CSV/PDF with Date, Description, Debit/Credit columns
    """,
)
async def import_preview(
    current_user: CurrentUser,
    db: DB,
    file: UploadFile = File(..., description="CSV file from PhonePe/GPay/HDFC/SBI"),
):
    """
    Parse uploaded CSV and return preview without saving anything.

    Why preview before confirm?
      Users can review, change categories, and uncheck rows they don't want.
      This prevents importing duplicates or unwanted transactions.
    """
    from app.expenses.import_service import parse_file

    content = await file.read()
    filename = file.filename or "upload.csv"
    cat_svc = CategoryService(db)
    categories = await cat_svc.list_categories(user_id=current_user.id)
    user_cats = [{"id": str(c.id), "name": c.name, "icon": c.icon} for c in categories]

    preview = parse_file(content, filename, user_cats)

    # Return JSON-serializable dict
    return {
        "format_detected": preview.format_detected,
        "total_rows": preview.total_rows,
        "debit_count": preview.debit_count,
        "credit_count": preview.credit_count,
        "skipped_count": preview.skipped_count,
        "transactions": [
            {
                "row_index": t.row_index,
                "date": t.date,
                "description": t.description,
                "amount": float(t.amount),
                "transaction_type": t.transaction_type,
                "reference": t.reference,
                "suggested_category_name": t.suggested_category_name,
                "suggested_category_id": t.suggested_category_id,
            }
            for t in preview.transactions
        ],
    }
