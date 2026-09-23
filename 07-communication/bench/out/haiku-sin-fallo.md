The problem is clear: **synchronous calls on the main thread cause the ANR**. In `PaymentViewModel.kt:118`, `provider.confirm()` runs on the main thread, blocking the UI. That's why it freezes.

**Immediate fix:**
- Move `provider.confirm()` to a background thread (Coroutine, Thread, or Executor)
- Use `viewModelScope.launch` or similar for network operations
- Update the UI only after the call finishes

**Why it doesn't reproduce in testing:**
- The test bench's network is probably faster
- Or there's less concurrent load
- In production, larger latencies (even 40ms can add up) make the blocking more evident

**Code review:**
```
PaymentViewModel.kt:118: 
// BAD: provider.confirm() // on main thread
// GOOD: viewModelScope.launch(Dispatchers.Default) { provider.confirm() }
```

Commit 7c1d0e9 introduced this regression. Reverting and reimplementing with async/await or Coroutines resolves the ANR immediately.
