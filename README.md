# Personal Finance Tracker

Self-hosted expense tracker: FastAPI + PostgreSQL backend, LLM-based expense categorization, and a daily summary endpoint that feeds an Android home-screen widget.

Full setup, architecture and example requests land with the packaging phase. See `PROGRESS.md` for what is built so far.

## Widget contract: `GET /summary/daily`

This is the only endpoint the widget calls, so its shape is frozen: fields may be added, never renamed or removed. All money values are strings with exactly two decimal places.

```
GET /summary/daily?tz=Europe/Dublin
```

| Query | Required | Meaning |
|---|---|---|
| `tz` | no (default `UTC`) | IANA timezone of the device. "Today" and "this month" are computed in this zone. Unknown zone → 422. |

```json
{
  "date": "2026-09-08",
  "timezone": "Europe/Dublin",
  "spent_today": "96.40",
  "spent_this_month": "296.40",
  "budget_total": "400.00",
  "remaining_total": "119.50",
  "over_budget": false,
  "categories": [
    {
      "id": 2,
      "name": "Groceries",
      "monthly_limit": "300.00",
      "spent": "165.50",
      "remaining": "134.50",
      "over_budget": false
    },
    {
      "id": 3,
      "name": "Eating out",
      "monthly_limit": "100.00",
      "spent": "115.00",
      "remaining": "-15.00",
      "over_budget": true
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `date` | Today in `timezone`. |
| `spent_today` | Sum of confirmed expenses dated today, all categories. |
| `spent_this_month` | Sum of confirmed expenses from the 1st of the month to today's month end, all categories. |
| `budget_total` | Sum of `monthly_limit` over categories that have one. |
| `remaining_total` | `budget_total` minus spending in budgeted categories only. Spending in a category with no limit does not reduce it. Negative when over. |
| `over_budget` | `remaining_total < 0`. |
| `categories` | Only categories with a `monthly_limit`, in id order. `remaining` may be negative; `over_budget` is `remaining < 0`. |

Pending (auto-ingested, unconfirmed) expenses are excluded from every total.

`GET /summary/monthly?month=YYYY-MM&tz=...` returns the same per-category shape for every category, limit or not, with `remaining: null` for unbudgeted ones.
