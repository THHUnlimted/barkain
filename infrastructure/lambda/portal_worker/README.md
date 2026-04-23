# Portal Worker Lambda — Deploy Runbook (Step 3g)

Cron-driven AWS Lambda that runs `backend/workers/portal_rates.py` every 6
hours, upserts cashback rates into `portal_bonuses`, and emails operators
via Resend when a portal returns zero rows for three consecutive runs.

## Why Lambda (and not EC2 / Fargate / a Hetzner box)

The worker runs ~30 seconds every 6 hours — 120 invocations × 30s ×
512 MB/month sits comfortably in the Lambda free tier. EC2 or Fargate
costs $5+/month for 24/7 uptime to do one minute of work per six hours.
A dedicated box is fine but adds a host to monitor for no benefit.

## Prerequisites

1. **AWS CLI configured** for an account with permission to create ECR
   repos, Lambda functions, IAM roles, and EventBridge rules.
2. **Docker installed** locally — the deploy script builds a `linux/amd64`
   container image.
3. **`DATABASE_URL` reachable from Lambda's network.** If the DB is in a
   VPC, the Lambda must be in the same VPC (use
   `AWSLambdaVPCAccessExecutionRole` on the IAM role and pass
   `--vpc-config` on first deploy). If the DB is on a managed host with a
   public endpoint (Railway/Render/Supabase), no VPC config is needed.
4. **An IAM role for the Lambda.** See §IAM below.
5. **A Secrets Manager secret holding `DATABASE_URL` and the Resend creds.**
   See §Secrets below.

## Secrets

Create one secret in AWS Secrets Manager named `barkain/portal-worker`
with this JSON shape:

```json
{
  "DATABASE_URL": "postgresql+asyncpg://user:pass@host:5432/dbname",
  "RESEND_API_KEY": "re_xxxxxxxxxxxxxxxx",
  "RESEND_ALERT_FROM": "alerts@barkain.app",
  "RESEND_ALERT_TO": "ops@barkain.app",
  "PORTAL_MONETIZATION_ENABLED": "true",
  "RAKUTEN_REFERRAL_URL": "https://www.rakuten.com/r/EXAMPLE",
  "BEFRUGAL_REFERRAL_URL": "https://www.befrugal.com/rs/EXAMPLE/",
  "TOPCASHBACK_FLEXOFFERS_PUB_ID": "",
  "TOPCASHBACK_FLEXOFFERS_LINK_TEMPLATE": ""
}
```

The Lambda reads the secret at cold-start. Update the JSON in Secrets
Manager and trigger a new invocation to pick up changes (a code redeploy
is not required for env changes).

## IAM

Create an IAM role `barkain-portal-worker-role` with these policies:

* **`AWSLambdaBasicExecutionRole`** (managed) — CloudWatch logs.
* **`AWSLambdaVPCAccessExecutionRole`** (managed) — only if Lambda is in
  a VPC.
* **Inline policy** for Secrets Manager read access:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-east-1:*:secret:barkain/portal-worker-*"
    }]
  }
  ```

Note the role's ARN — you'll pass it via `LAMBDA_ROLE_ARN` to the deploy
script.

## Deploy

```bash
export AWS_REGION=us-east-1
export LAMBDA_ROLE_ARN="arn:aws:iam::123456789012:role/barkain-portal-worker-role"
export SECRETS_ARN="arn:aws:secretsmanager:us-east-1:123456789012:secret:barkain/portal-worker-AbCdEf"

./deploy.sh
```

The script is idempotent — re-run after every code or dep change. It
creates (or updates):

1. ECR repo `barkain-portal-worker`
2. Container image (built locally, pushed to ECR)
3. Lambda function `barkain-portal-worker` (image package, 300s timeout,
   512 MB memory)
4. EventBridge rule `barkain-portal-cron` (`cron(0 */6 * * ? *)`)
5. EventBridge → Lambda invoke permission

## Verify

```bash
aws lambda invoke \
  --function-name barkain-portal-worker \
  --invocation-type Event \
  --region us-east-1 /tmp/out.json

aws logs tail /aws/lambda/barkain-portal-worker --region us-east-1 --since 5m
```

Look for `portal scrape complete: {...}` in the logs. Each portal entry
shows the row count — `rakuten: 30, topcashback: 0, befrugal: 25` means
TopCashback returned zero on this run (counter incremented; alert fires
on the third consecutive empty run).

## Update env values

Update the JSON in Secrets Manager — no redeploy needed. Lambda picks up
the new values on the next cold start (or invoke `aws lambda
update-function-configuration --environment` to force a fresh container).

## Cost estimate

* 120 invocations/month × 30s × 512 MB = **~7 GB-seconds/month**
* Lambda free tier covers 400,000 GB-seconds/month — effectively free
* CloudWatch logs: ~5 MB/month at $0.50/GB → **negligible**
* ECR storage: one image at ~150 MB → **$0.015/month**

Total: **~$0/month** unless the cadence changes materially.

## Rollback

```bash
aws events disable-rule --name barkain-portal-cron --region us-east-1
```

Stops scheduled invocations without deleting anything. The last good
`portal_bonuses` rows continue to serve the iOS pill.
