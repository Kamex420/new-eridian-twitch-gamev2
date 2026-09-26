# Production balance validation

The full regression suite passed: 693 tests, two dependency deprecation warnings, 99.32 seconds. A subsequent change expressed the 70-percent sale-price calculation using integer arithmetic to avoid floating-point rounding; 27 focused production and identity tests passed afterward in 3.32 seconds. Compilation and whitespace checks passed.

New coverage checks demand-based 5/10/15 base batches, station-adjusted 5–20 material outputs, finished outputs of one, untouched extraction yields, workstation access, exact input/output inventory deltas, sell-only purchase rejection, complete catalog pricing, and the purchase/resale spread. Existing queue tests now verify actual station-adjusted batch totals rather than the unmodified source quantity. Market tests verify the newly authorized buyback and exact player balances.

The source catalog and legacy Discord options fixture retain their previous SHA-256 values. No live Railway, PostgreSQL, Discord, or Twitch verification was performed. The two warnings concern Starlette/AnyIO and discord.py audioop deprecations.
