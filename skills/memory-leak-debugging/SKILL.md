---
name: memory-leak-debugging
description: Diagnose memory leaks, object retention, and uncollected references.
tags: [performance, memory, profiling, speed]
---

# Memory Leak Debugging

## Principles
1. Check for unbound collections: global caches, module-level lists, and event listeners that never unregister.
2. Replace manual unbounded dictionary caches with LRU cache or weak references (`weakref.WeakValueDictionary`).
3. Clean up large buffers after streaming or processing data.
4. Verify peak memory drop or garbage collection behavior.
