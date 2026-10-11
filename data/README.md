# Data

`sample/` holds the three synthetic CSV files used by the original prototype (cloud_spend.csv, customer_metrics.csv,
product_logs.csv): 90 days (2025-01-01 to 2025-03-31), 24 customers, 2 products, 3 clouds, 4 spend categories. The files
are synthetic and small (total spend about 4,269 USD). Spend is zero for the whole of January. They contain no injected
anomalies, so detections on them are onboarding ramps, not labeled incidents. Use them to try the interface and loaders.

The controlled experiment does not read these files. It generates labeled datasets with `gcsi.synth` (see the README).

`focus_sample/` is empty. To try the FOCUS loader, download a sample from
https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data (CC BY 4.0, attribution required) and run
`gcsi detect --input <file.csv> --format focus`.
