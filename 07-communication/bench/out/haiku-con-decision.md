Use Room and write the state before every critical operation between sending and confirmation.

Room offers built-in transactions (guarantees you write before acting), is queryable after a crash, and the team already uses it.

What matters isn't where you store, but when you write.

| Option | Risk |
|--------|--------|
| SharedPreferences | Not transactional; can lose state between steps |
| Write-ahead log | Unnecessary complexity; Room already does this |
| Room | Built-in transactions, queryable, team already uses it |

I need from you: if the provider confirms but your app dies before writing to Room, how do you detect it? Do you have a validation mechanism with the provider on startup?

## Technical detail

[Recommended]: states in Room: STARTED → SENT_TO_PROVIDER → CONFIRMED_BY_PROVIDER → CONFIRMED_LOCALLY (or FAILED at any point).

[Critical]: update Room before sending to the provider and before confirming locally. If the process dies, you re-read the table and know exactly where you were.

[Assumed]: the provider returns a unique payment ID.

[Not tested]: validation after a crash (query the provider? trust Room?). Concurrency across multiple simultaneous payments.
