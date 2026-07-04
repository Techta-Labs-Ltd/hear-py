# Hear Alexa skill — Python, deployed as a Lambda container image.
# Base is the official AWS Lambda Python 3.12 runtime (x86_64).
FROM public.ecr.aws/lambda/python:3.12

# 1) Dependencies first (better layer caching)
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN python -m pip install --no-cache-dir -r requirements.txt

# 2) Optional spaCy model, installed as a wheel (avoids the spaCy CLI, which
#    needs `click`). The NLP layer falls back to spacy.blank("en") if it's
#    missing, so a failure here must not break the build.
RUN python -m pip install --no-cache-dir \
    "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl" \
    || true

# 3) Application source
COPY main.py ${LAMBDA_TASK_ROOT}/
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY config/ ${LAMBDA_TASK_ROOT}/config/

# Lambda handler (module.function)
CMD ["main.handler"]
