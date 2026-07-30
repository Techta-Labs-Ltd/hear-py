FROM public.ecr.aws/lambda/python:3.12
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN python -m pip install --no-cache-dir -r requirements.txt
ENV FASTEMBED_CACHE_PATH=/opt/hear-semantic-models
ENV LITELLM_LOCAL_MODEL_COST_MAP=True
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/hear-semantic-models').embed(['hear semantic router warmup']))"
RUN python -m pip install --no-cache-dir \
    "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl" \
    || true
COPY main.py ${LAMBDA_TASK_ROOT}/
COPY en-GB.json ${LAMBDA_TASK_ROOT}/
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY config/ ${LAMBDA_TASK_ROOT}/config/

ENV HEAR_SEMANTIC_ROUTER_INDEX_PATH=/opt/hear-semantic-index.npz
RUN python -c "from src.services.semantic_routing import write_semantic_index; write_semantic_index()"

ENV HEAR_TAXONOMY_BUNDLE_DIR=/opt/hear-taxonomy
RUN HEAR_TAXONOMY_CACHE_DIR=/opt/hear-taxonomy \
    python -c "from src.resolver.taxonomy import taxonomy_manager; taxonomy_manager.refresh()"

CMD ["main.handler"]
