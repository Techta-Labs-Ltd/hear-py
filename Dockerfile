FROM public.ecr.aws/lambda/python:3.12
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN python -m pip install --no-cache-dir -r requirements.txt
ENV FASTEMBED_CACHE_PATH=/opt/hear-semantic-models
ENV LITELLM_LOCAL_MODEL_COST_MAP=True
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/hear-semantic-models').embed(['hear semantic router warmup']))"
COPY main.py ${LAMBDA_TASK_ROOT}/
COPY en-GB.json ${LAMBDA_TASK_ROOT}/
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY config/ ${LAMBDA_TASK_ROOT}/config/

ENV HEAR_SEMANTIC_ROUTER_INDEX_PATH=/opt/hear-semantic-index.npz
RUN python -c "from src.services.semantic_routing import write_semantic_index; write_semantic_index()"

CMD ["main.handler"]
