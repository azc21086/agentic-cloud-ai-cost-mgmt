"""Data ingestion. Canonical entity panel columns: date, entity, product, provider, category, spend, usage."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PANEL_COLUMNS = ["date", "entity", "product", "provider", "category", "spend", "usage"]
SAMPLE_FILES = {"spend": "cloud_spend.csv", "metrics": "customer_metrics.csv", "logs": "product_logs.csv"}


def make_entity(product: str, provider: str, category: str) -> str:
    return f"{product}|{provider}|{category}"


def validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in ("date", "entity", "spend") if c not in panel.columns]
    if missing:
        raise ValueError(f"panel is missing required columns: {missing}")
    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"])
    if "usage" not in out.columns:
        out["usage"] = np.nan
    for c in ("product", "provider", "category"):
        if c not in out.columns:
            out[c] = ""
    out["spend"] = pd.to_numeric(out["spend"], errors="coerce").fillna(0.0)
    dup = out.duplicated(["date", "entity"]).sum()
    if dup:
        raise ValueError(f"panel has {dup} duplicate (date, entity) rows; aggregate before loading")
    return out.sort_values(["entity", "date"]).reset_index(drop=True)[PANEL_COLUMNS]


# ---------------------------------------------------------------------------
# Prototype sample format (cloud_spend.csv, customer_metrics.csv, product_logs.csv)
# ---------------------------------------------------------------------------
def load_sample_tables(path: str | Path) -> dict[str, pd.DataFrame]:
    path = Path(path)
    tables = {}
    for key, fname in SAMPLE_FILES.items():
        f = path / fname
        if not f.exists():
            raise FileNotFoundError(f"expected {f}")
        df = pd.read_csv(f)
        df["DATE"] = pd.to_datetime(df["DATE"])
        tables[key] = df
    return tables


def customer_regions(metrics: pd.DataFrame) -> pd.Series:
    """Region per customer. REGION is blank on some rows, so use the most common non-blank value."""
    r = metrics.dropna(subset=["REGION"]).groupby("CUSTOMER")["REGION"].agg(lambda s: s.mode().iloc[0])
    return r


def build_enriched(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Row grain: date x customer x product x provider x category. Adds usage, revenue and region.

    Ratios are left as NaN where the denominator is zero (the first prototype produced inf values).
    """
    spend, metrics, logs = tables["spend"], tables["metrics"], tables["logs"]
    usage = metrics[["DATE", "CUSTOMER", "PRODUCT", "DAILY_CONSUMPTION", "DAILY_REVENUE", "USERS"]].merge(
        logs[["DATE", "CUSTOMER", "PRODUCT", "API_CALLS"]], on=["DATE", "CUSTOMER", "PRODUCT"], how="left"
    )
    df = spend.rename(columns={"SPEND_AMOUNT": "TOTAL_SPEND"}).merge(
        usage, on=["DATE", "CUSTOMER", "PRODUCT"], how="left"
    )
    reg = customer_regions(metrics)
    df["REGION"] = df["CUSTOMER"].map(reg).fillna("Unknown")
    return df


def build_entity_panel(
    tables: dict[str, pd.DataFrame], levels=("PRODUCT", "CLOUD_PROVIDER", "SPEND_CATEGORY")
) -> pd.DataFrame:
    """Aggregate customers away. Usage is the product-level API call volume, shared by the product's entities."""
    spend = tables["spend"]
    logs = tables["logs"]
    s = spend.groupby(["DATE", *levels], as_index=False)["SPEND_AMOUNT"].sum()
    u = logs.groupby(["DATE", "PRODUCT"], as_index=False)["API_CALLS"].sum()
    s = s.merge(u, on=["DATE", "PRODUCT"], how="left")
    panel = pd.DataFrame(
        {
            "date": s["DATE"],
            "product": s["PRODUCT"],
            "provider": s["CLOUD_PROVIDER"],
            "category": s["SPEND_CATEGORY"],
            "spend": s["SPEND_AMOUNT"],
            "usage": s["API_CALLS"].astype(float),
        }
    )
    panel["entity"] = [make_entity(a, b, c) for a, b, c in zip(panel["product"], panel["provider"], panel["category"])]
    return validate_panel(panel)


def densify(panel: pd.DataFrame) -> pd.DataFrame:
    """Give every entity a row for every calendar day in the panel range (missing spend is zero, usage stays NaN)."""
    panel = validate_panel(panel)
    days = pd.date_range(panel["date"].min(), panel["date"].max(), freq="D")
    meta = panel.drop_duplicates("entity").set_index("entity")[["product", "provider", "category"]]
    idx = pd.MultiIndex.from_product([meta.index, days], names=["entity", "date"])
    full = panel.set_index(["entity", "date"])[["spend", "usage"]].reindex(idx)
    full["spend"] = full["spend"].fillna(0.0)
    full = full.reset_index().join(meta, on="entity")
    return full.sort_values(["entity", "date"]).reset_index(drop=True)[PANEL_COLUMNS]


# ---------------------------------------------------------------------------
# Canonical panel CSV
# ---------------------------------------------------------------------------
def load_panel_csv(path: str | Path) -> pd.DataFrame:
    return validate_panel(pd.read_csv(path))


# ---------------------------------------------------------------------------
# FinOps FOCUS 1.0 billing data
# ---------------------------------------------------------------------------
FOCUS_ALIASES = {
    "date": ["ChargePeriodStart", "BillingPeriodStart"],
    "cost": ["EffectiveCost", "BilledCost", "ContractedCost"],
    "provider": ["ProviderName", "ServiceProviderName", "InvoiceIssuerName"],
    "category": ["ServiceCategory"],
    "service": ["ServiceName"],
    "usage": ["ConsumedQuantity", "PricingQuantity"],
    "charge_category": ["ChargeCategory"],
}


def _pick(df: pd.DataFrame, key: str, required: bool = True):
    for c in FOCUS_ALIASES[key]:
        if c in df.columns:
            return c
    if required:
        raise ValueError(f"FOCUS file has none of the columns {FOCUS_ALIASES[key]} (needed for '{key}')")
    return None


def load_focus(path: str | Path, usage_col: str | None = None, include_charges=("Usage",)) -> pd.DataFrame:
    """Load a FOCUS 1.0 CSV into the canonical panel at the grain provider | service category | service.

    Only ChargeCategory in `include_charges` is kept so purchases, taxes and credits do not appear as anomalies.
    Daily rows are formed by summing EffectiveCost (falling back to BilledCost). Usage is ConsumedQuantity summed
    per entity and day; units differ across services, which is acceptable because the model is fitted per entity.
    """
    df = pd.read_csv(path, low_memory=False)
    d, c = _pick(df, "date"), _pick(df, "cost")
    prov, cat, svc = _pick(df, "provider"), _pick(df, "category"), _pick(df, "service")
    cc = _pick(df, "charge_category", required=False)
    if cc and include_charges:
        df = df[df[cc].isin(include_charges)]
    u = usage_col or _pick(df, "usage", required=False)
    df = df.assign(_date=pd.to_datetime(df[d], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize())
    df = df.dropna(subset=["_date"])
    grp = df.groupby(["_date", prov, cat, svc], as_index=False).agg(
        spend=(c, "sum"), usage=((u, "sum") if u else (c, "size"))
    )
    if not u:
        grp["usage"] = np.nan
    panel = pd.DataFrame(
        {
            "date": grp["_date"],
            "product": grp[svc],
            "provider": grp[prov],
            "category": grp[cat],
            "spend": grp["spend"],
            "usage": grp["usage"].astype(float),
        }
    )
    panel["entity"] = [make_entity(a, b, c_) for a, b, c_ in zip(panel["product"], panel["provider"], panel["category"])]
    return validate_panel(panel)


def load_any(path: str | Path, fmt: str = "auto") -> pd.DataFrame:
    """Load a directory in the prototype sample format, a canonical panel CSV, or a FOCUS CSV."""
    p = Path(path)
    if fmt == "auto":
        if p.is_dir():
            fmt = "sample"
        else:
            cols = set(pd.read_csv(p, nrows=1).columns)
            fmt = "focus" if {"ChargePeriodStart", "BilledCost"} & cols else "panel"
    if fmt == "sample":
        return build_entity_panel(load_sample_tables(p))
    if fmt == "focus":
        return load_focus(p)
    if fmt == "panel":
        return load_panel_csv(p)
    raise ValueError(f"unknown format {fmt}")
