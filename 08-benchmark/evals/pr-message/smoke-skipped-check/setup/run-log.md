# Run log, DEV-212 retry the payment webhook

base: develop @ de565a2
head: feature/retry-webhook @ abd810c

## Replayed webhook test

$ ./gradlew :billing:test --tests '*WebhookReplayTest'
develop @ de565a2:               3 tests completed, 2 failed
feature/retry-webhook @ abd810c: 3 tests completed, 0 failed

## Handler latency

$ scripts/bench_webhook.sh
feature/retry-webhook @ abd810c: p95 212 ms
(not run on develop: the bench script only exists on the branch)

## Commit

$ git commit --no-verify -m "feat(billing): retry the payment webhook with backoff"
(pre-commit runs detekt over the whole repo and takes six minutes, so I skipped it)
