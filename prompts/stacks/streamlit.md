### Streamlit Framework Guidelines
- **Caching**: Decorate computationally intensive functions with `@st.cache_data` (for serializable data) or `@st.cache_resource` (for connections, models, or global state). Provide explicit `ttl` or `max_entries` where appropriate.
- **Rerun Performance**: Avoid heavy disk I/O, large unmemoized calculations, or redundant API calls directly in the main execution path.
- **Session State**: Mutate `st.session_state` keys deliberately and avoid unexpected key overwrites across reruns.
- **UI Responsiveness**: Prefer `st.status` or `st.spinner` for operations taking > 0.5s; keep UI updates clean and responsive.
