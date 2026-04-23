# AWS Lambda container image for the portal scrape worker (Step 3g).
#
# Built and pushed to ECR by ./deploy.sh; invoked every 6 hours by an
# EventBridge cron rule. See README.md for the full deploy runbook.

FROM public.ecr.aws/lambda/python:3.12

# Layer 1 — pinned deps (cached unless requirements.txt changes).
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Layer 2 — backend source. We only need `workers/` and `modules/m13_portal/`
# + their transitive deps; copying the whole backend/ keeps the Dockerfile
# simple and the resulting image is still well under Lambda's 10 GB limit.
COPY backend/ ${LAMBDA_TASK_ROOT}/backend/

# Layer 3 — handler at the image root so Lambda finds it via the default
# entrypoint (`handler.lambda_handler`).
COPY handler.py ${LAMBDA_TASK_ROOT}/

CMD ["handler.lambda_handler"]
