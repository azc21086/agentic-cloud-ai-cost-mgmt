"""Descriptive insights and natural-language Q&A over the enriched prototype tables (the original GCSI features).

Fixes relative to the first prototype: ratios are ratios of sums (not means of row ratios), volatility ignores tiny
bases instead of reporting inf, and the language model is given a computed fact table and told not to invent numbers.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd


def _safe_div(a, b):
    return np.where(np.asarray(b) > 0, np.asarray(a) / np.where(np.asarray(b) > 0, b, 1), np.nan)


def product_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("PRODUCT").agg(
        spend=("TOTAL_SPEND", "sum"), revenue=("DAILY_REVENUE", "sum"), consumption=("DAILY_CONSUMPTION", "sum")
    )
    # revenue and consumption repeat across provider and category rows, so take them from the unique customer-day grain
    uniq = df.drop_duplicates(["DATE", "CUSTOMER", "PRODUCT"])
    rc = uniq.groupby("PRODUCT").agg(revenue=("DAILY_REVENUE", "sum"), consumption=("DAILY_CONSUMPTION", "sum"))
    g["revenue"], g["consumption"] = rc["revenue"], rc["consumption"]
    g["revenue_to_cost"] = _safe_div(g["revenue"], g["spend"])
    g["cost_per_consumption"] = _safe_div(g["spend"], g["consumption"])
    return g.round(4)


def weekly_volatility(df: pd.DataFrame, min_base_usd: float = 1.0, top: int = 5) -> pd.DataFrame:
    """Week-over-week spend change by customer for the last two complete weeks; bases below min_base_usd are skipped."""
    d = df.copy()
    d["week"] = d["DATE"].dt.to_period("W").dt.start_time
    w = d.groupby(["CUSTOMER", "week"])["TOTAL_SPEND"].sum().unstack("week")
    if w.shape[1] < 3:
        return pd.DataFrame(columns=["CUSTOMER", "prior_week_usd", "last_week_usd", "change_pct"])
    last, prior = w.iloc[:, -2], w.iloc[:, -3]  # last column may be a partial week
    out = pd.DataFrame({"prior_week_usd": prior, "last_week_usd": last})
    out = out[out["prior_week_usd"] >= min_base_usd]
    out["change_pct"] = 100 * (out["last_week_usd"] - out["prior_week_usd"]) / out["prior_week_usd"]
    return out.reindex(out["change_pct"].abs().sort_values(ascending=False).index).head(top).round(2).reset_index()


def precomputed(df: pd.DataFrame) -> dict:
    return {
        "product_summary": product_summary(df),
        "volatility": weekly_volatility(df),
        "provider_spend": df.groupby("CLOUD_PROVIDER")["TOTAL_SPEND"].sum().round(2).sort_values(ascending=False),
        "category_spend": df.groupby("SPEND_CATEGORY")["TOTAL_SPEND"].sum().round(2).sort_values(ascending=False),
        "region_spend": df.groupby("REGION")["TOTAL_SPEND"].sum().round(2).sort_values(ascending=False),
    }


def render_precomputed(p: dict) -> str:
    ps = p["product_summary"]
    lines = ["Product summary (USD; revenue-to-cost is a ratio of sums)", ps[["spend", "revenue", "revenue_to_cost", "cost_per_consumption"]].to_string(), ""]
    lines += ["Largest week-over-week spend changes by customer (bases under 1 USD skipped)"]
    lines += [p["volatility"].to_string(index=False) if len(p["volatility"]) else "not enough weeks of data", ""]
    lines += ["Spend by cloud provider (USD)", p["provider_spend"].to_string(), ""]
    lines += ["Spend by region (USD; 'Unknown' where the customer has no region on file)", p["region_spend"].to_string()]
    return "\n".join(lines)


KINDS = ("roi", "provider", "category", "region", "product", "usage", "total")


def classify(question: str) -> str:
    q = question.lower()
    for kind, keys in (
        ("roi", ("roi", "revenue", "return")),
        ("usage", ("usage", "consumption", "scatter")),
        ("provider", ("provider", "cloud", "aws", "azure", "google")),
        ("category", ("category", "compute", "storage", "network", "observability")),
        ("region", ("region", "emea", "apac", "latam")),
        ("product", ("product", "alpha", "beta")),
    ):
        if any(k in q for k in keys):
            return kind
    return "total"


def facts_for(df: pd.DataFrame, kind: str) -> dict:
    p = precomputed(df)
    f = {
        "period": [str(df["DATE"].min().date()), str(df["DATE"].max().date())],
        "total_spend_usd": round(float(df["TOTAL_SPEND"].sum()), 2),
        "product_summary": json.loads(p["product_summary"].reset_index().to_json(orient="records")),
    }
    key = {"provider": "provider_spend", "category": "category_spend", "region": "region_spend"}.get(kind)
    if key:
        f[key] = {k: float(v) for k, v in p[key].items()}
    return f


def make_chart(df: pd.DataFrame, kind: str):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    col = {"provider": "CLOUD_PROVIDER", "category": "SPEND_CATEGORY", "region": "REGION", "product": "PRODUCT"}.get(kind)
    if kind == "roi":
        s = product_summary(df)["revenue_to_cost"]
        s.plot.bar(ax=ax, color="#3b6ea5")
        ax.set_ylabel("Revenue / spend")
        ax.set_title("Revenue-to-cost ratio by product (ratio of sums)")
    elif kind == "usage":
        u = df.groupby(["DATE", "PRODUCT"], as_index=False).agg(spend=("TOTAL_SPEND", "sum"), calls=("API_CALLS", "sum"))
        for prod, g in u.groupby("PRODUCT"):
            ax.scatter(g["calls"], g["spend"], s=12, alpha=0.7, label=prod)
        ax.set_xlabel("API calls per day")
        ax.set_ylabel("Spend per day (USD)")
        ax.set_title("Daily spend versus usage")
        ax.legend()
    else:
        t = df.groupby("DATE")["TOTAL_SPEND"].sum() if col is None else df.groupby(["DATE", col])["TOTAL_SPEND"].sum().unstack(col)
        t.plot(ax=ax)
        ax.set_ylabel("Spend per day (USD)")
        ax.set_title("Total spend over time" + (f" by {col.lower().replace('_', ' ')}" if col else ""))
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig


GROUNDING = (
    "You are a cloud financial analyst. Answer using ONLY the numbers in the fact table. Amounts are USD. "
    "Do not invent figures. If the table cannot answer, say so. Keep the answer under 180 words."
)


def narrate(question: str, facts: dict, llm=None) -> str:
    """Answer in prose. With no model, return a plain templated summary of the computed facts."""
    if llm is not None:
        try:
            r = llm.complete(GROUNDING, f"Question: {question}\nFact table:\n{json.dumps(facts, sort_keys=True)}")
            if r.error:
                return f"(model call failed: {r.error}) " + narrate(question, facts, None)
            if r.text and not r.text.strip().startswith("{"):
                return r.text
        except Exception as e:  # network or key problems should not break the interface
            return f"(model call failed: {type(e).__name__}) " + narrate(question, facts, None)
    lines = [f"Period {facts['period'][0]} to {facts['period'][1]}; total spend {facts['total_spend_usd']:,.2f} USD."]
    for r in facts["product_summary"]:
        lines.append(
            f"{r['PRODUCT']}: spend {r['spend']:,.2f} USD, revenue-to-cost {r['revenue_to_cost']:.2f}, "
            f"cost per consumption unit {r['cost_per_consumption']:.4f}."
        )
    for k in ("provider_spend", "category_spend", "region_spend"):
        if k in facts:
            lines.append(k.replace("_", " ").capitalize() + ": " + ", ".join(f"{a} {b:,.2f}" for a, b in facts[k].items()) + " USD.")
    return "\n".join(lines)
