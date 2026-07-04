# Hear Alexa skill — Python, deployed as a Lambda container image.
# Base is the official AWS Lambda Python 3.12 runtime (x86_64).
FROM public.ecr.aws/lambda/python:3.12

# 1) Dependencies first (better layer caching)
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN python -m pip install --no-cache-dir -r requirements.txt

# 2) Optional spaCy model. The NLP layer falls back to spacy.blank("en") if it
#    is missing, so a download failure must not break the build.
RUN python -m spacy download en_core_web_sm || true

# 3) Application source
COPY main.py ${LAMBDA_TASK_ROOT}/
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY config/ ${LAMBDA_TASK_ROOT}/config/

# Lambda handler (module.function)
CMD ["main.handler"]
