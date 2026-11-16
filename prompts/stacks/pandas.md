### Pandas Optimization Guidelines
- **Vectorization**: Replace `.apply()`, `.applymap()`, and explicit row iterations (`.iterrows()`, `.itertuples()`) with vectorized NumPy/Pandas operations or `.map(dict)` for lookups.
- **Datetime Operations**: Prefer numeric arithmetic or `.dt.normalize()` over expensive string formatting (`.dt.strftime`, `.dt.date`).
- **Memory & Types**: Specify `dtype` and `usecols` on read operations (`pd.read_csv`, `pd.read_excel`) to reduce peak memory consumption. Avoid unnecessary `df.copy()`.
- **Baseline Equality**: Verify that optimizations preserve identical column types, index values, and NaN/NaT representations via `pd.testing.assert_frame_equal` or `assert_series_equal`.
