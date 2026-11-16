### FastAPI & Modern Web API Guidelines
- **Asynchronous Execution**: Declare I/O-bound route handlers with `async def`. For blocking synchronous CPU/disk operations, use standard `def` so FastAPI runs them in an external thread pool.
- **Validation**: Enforce explicit Pydantic schemas for request bodies and response models.
- **Dependencies**: Use FastAPI's `Depends` system for authentication, database sessions, and configuration injection.
