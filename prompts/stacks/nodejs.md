### TypeScript & Node.js Guidelines
- **Type Safety**: Avoid `any`; use strict typing, union types, and type guards.
- **Async Handling**: Use clean `async/await` and avoid unhandled Promise rejections. Avoid blocking the event loop with synchronous heavy operations.
- **Component Design**: Keep UI components modular, accessible (WCAG), and decouple data fetching from presentation.
