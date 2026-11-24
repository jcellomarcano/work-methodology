# Setup interview: shop-api

Repo: `~/code/shop-api`. Answers I gave on Monday, in the order you asked.

1. Which properties matter here, and in what order do they break a tie?
   Data integrity first, then Security, then Availability. Performance comes last.

2. Which of those are critical, the ones that need an invariant in the card?
   Not sure yet. Dana owns that call and she is out until Thursday; ask me again then.

3. Which paths are critical?
   `src/payments/` and `src/refunds/`.

4. Ticket prefixes?
   `PAY` and `SHOP`.

5. Main language of the code?
   `kotlin`.

6. Which agent runtime do you use?
   Only Claude Code, nobody here uses the other two.

7. Where should the audit folder go?
   `~/shop-audit`.

8. Who reviews?
   Dana and Luis, two approvals on anything under payments.

9. CI?
   GitHub Actions; the build takes about twelve minutes.
