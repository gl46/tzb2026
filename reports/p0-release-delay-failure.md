# P0 release-delay injection — verified failure

Date: 2026-07-15, Asia/Shanghai

On node2, the bounded P0 controller completed approach, close, constrained attach, lift, move,
and hand-open actions. The detach command was deliberately withheld after the hand opened. At
end-of-run cleanup, publishing detach emitted the expected `detached` state event, proving the
object was still constrained before cleanup.

Result: **VERIFIED_RELEASE_DELAY_FAILURE**. The task is labelled unsuccessful because release was
not observed during the task, even though arm and hand actions reported success.
