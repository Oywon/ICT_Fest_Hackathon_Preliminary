# Bug Report

## 1) Datetime parsing did not normalize timezone-aware input correctly
- File: app/timeutils.py
- Function: parse_input_datetime
- Line number: app/timeutils.py:5-17
- Problem: ISO 8601 values ending in Z were not converted correctly to UTC before storage. The implementation also did not consistently normalize offset-aware datetimes to UTC.
- Why it fails: booking creation and comparisons could use the wrong instant when a client sends a timezone-aware timestamp.
- How hidden tests detect it: they send booking payloads with offsets and expect the booking to be stored and compared in UTC.
- Minimal fix: normalize Z to +00:00 and convert timezone-aware datetimes to UTC before stripping the timezone.

## 2) Booking validation used the wrong future-time rule
- File: app/routers/bookings.py
- Function: create_booking
- Line number: app/routers/bookings.py:78-131
- Problem: the creation logic did not enforce the strict “start time must be strictly in the future” rule.
- Why it fails: hidden tests expect any booking with a start time less than or equal to the current UTC time to be rejected.
- How hidden tests detect it: they submit bookings with a start equal to the current time or just slightly in the past and expect a 400 error.
- Minimal fix: reject any booking whose start time is less than or equal to the current UTC time.

## 3) Booking overlap logic was incorrect
- File: app/routers/bookings.py
- Function: _has_conflict
- Line number: app/routers/bookings.py:46-56
- Problem: the overlap condition used inclusive comparisons, which incorrectly treated back-to-back bookings as conflicts.
- Why it fails: the spec requires overlap only when existing.start < new.end and new.start < existing.end.
- How hidden tests detect it: they create adjacent bookings and expect them to be accepted.
- Minimal fix: use the strict overlap condition.

## 4) Booking duration validation was incorrect
- File: app/routers/bookings.py
- Function: create_booking
- Line number: app/routers/bookings.py:91-101
- Problem: the code did not correctly enforce whole-hour durations or the minimum/maximum booking window.
- Why it fails: the spec requires durations of at least 1 hour, at most 8 hours, and only whole-hour values.
- How hidden tests detect it: they submit 30-minute, 9-hour, or non-whole-hour bookings and expect 400 INVALID_BOOKING_WINDOW.
- Minimal fix: compute duration in seconds, require divisibility by 3600, and enforce the min/max bounds.

## 5) Booking creation was not safe under concurrency
- File: app/routers/bookings.py
- Function: create_booking
- Line number: app/routers/bookings.py:78-131
- Problem: concurrent booking requests could race through conflict and quota checks.
- Why it fails: hidden tests issue multiple simultaneous requests and expect conflict and quota enforcement to remain correct.
- How hidden tests detect it: they create several concurrent bookings for the same room or same user and verify that overbooking and quota overruns are blocked.
- Minimal fix: serialize booking creation with a lock around the full validation-and-insert path.

## 6) Booking listing pagination and ordering were wrong
- File: app/routers/bookings.py
- Function: list_bookings
- Line number: app/routers/bookings.py:134-154
- Problem: the endpoint sorted descending by start time and used the wrong offset formula.
- Why it fails: the spec requires ascending order by start time and stable pagination without skipped or repeated items.
- How hidden tests detect it: they request multiple pages and compare the returned item sequence.
- Minimal fix: sort by start_time asc, id asc and offset by (page - 1) * limit.

## 7) Booking detail access incorrectly allowed cross-tenant reads
- File: app/routers/bookings.py
- Function: get_booking
- Line number: app/routers/bookings.py:157-183
- Problem: the logic did not enforce the rule that members may only see their own bookings and admins only their org's bookings.
- Why it fails: a member could access another member’s booking if the room belonged to the same org.
- How hidden tests detect it: they request another user’s booking ID and expect 404 BOOKING NOT FOUND.
- Minimal fix: enforce ownership for members and org scoping for admins.

## 8) Cancellation policy used the wrong refund percentage
- File: app/routers/bookings.py
- Function: cancel_booking
- Line number: app/routers/bookings.py:186-233
- Problem: the refund logic returned 50% refund for notice less than 24 hours, while the spec requires 0%.
- Why it fails: the grader checks the exact refund percent and refund amount.
- How hidden tests detect it: they cancel a booking with less than 24 hours notice and compare the response.
- Minimal fix: set the refund percentage to 0 for notice under 24 hours.

## 9) Refund amount rounding was incorrect
- File: app/services/refunds.py
- Function: calculate_refund_amount_cents
- Line number: app/services/refunds.py:14-15
- Problem: the refund amount was computed with a rounding method that did not match the required half-up rule.
- Why it fails: refund amounts can be off by one cent.
- How hidden tests detect it: they compare the cancel response against the stored refund log for edge cases.
- Minimal fix: use integer rounding that matches half-up behavior.

## 10) Auth logout invalidation was checking the wrong token identifier
- File: app/auth.py
- Function: get_token_payload
- Line number: app/auth.py:89-99
- Problem: logout invalidation tracked revoked tokens by the wrong claim, so subsequent use of the same token could slip through.
- Why it fails: after logout, a previously issued access token should be rejected with 401.
- How hidden tests detect it: they log out and then reuse the access token.
- Minimal fix: store and check the JWT jti claim.

## 11) Refresh-token rotation was not enforced correctly
- File: app/routers/auth.py
- Function: refresh
- Line number: app/routers/auth.py:77-92
- Problem: the refresh endpoint did not enforce single-use refresh-token behavior correctly.
- Why it fails: the grader reuses a refresh token and expects the second use to fail.
- How hidden tests detect it: they refresh twice with the same refresh token and expect the second attempt to be rejected.
- Minimal fix: revoke the presented refresh token after use and reject reuse via the revoked-token set.

## 12) Duplicate registration was handled incorrectly
- File: app/routers/auth.py
- Function: register
- Line number: app/routers/auth.py:23-55
- Problem: duplicate usernames in the same organization were not treated as a hard conflict.
- Why it fails: the spec requires 409 USERNAME TAKEN for duplicate usernames.
- How hidden tests detect it: they register the same username twice in the same org and expect the second call to fail.
- Minimal fix: raise AppError(409, "USERNAME_TAKEN", ...) when the username already exists in the org.

## 13) Shared in-memory state was not protected against concurrent access
- File: app/cache.py
- Function: cache operations
- Line number: app/cache.py:8-34
- Problem: the report and availability caches were mutated from multiple threads without synchronization.
- Why it fails: concurrent create/cancel requests could leave stale or inconsistent cache contents.
- How hidden tests detect it: they make parallel booking changes and immediately request report/availability data.
- Minimal fix: guard all cache reads/writes/invalidation with a lock.

## 14) Shared counters and stateful services were not thread-safe
- File: app/services/reference.py, app/services/stats.py, app/services/ratelimit.py
- Function: next_reference_code, record_create, record_cancel, record_and_check
- Line number: app/services/reference.py:9-24; app/services/stats.py:9-36; app/services/ratelimit.py:10-29
- Problem: the shared counters/buckets were not protected against simultaneous access.
- Why it fails: concurrent requests can produce duplicate reference codes, inconsistent room stats, or broken rate limiting.
- How hidden tests detect it: they send bursts of simultaneous booking requests and check uniqueness and limit behavior.
- Minimal fix: serialize access to these shared state structures with a lock.
