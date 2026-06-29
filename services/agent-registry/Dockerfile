FROM repo.bank.com.pl/zrai-docker-remote-dev/python:3.11-slim

WORKDIR /app

COPY shared/ /app/shared/

COPY services/agent-registry/requirements.txt .
RUN --mount=type=secret,id=pip_conf,target=/etc/pip.conf \
    pip install \
    --trusted-host repo.bank.com.pl \
    --trusted-host pypi.org \
    --trusted-host files.pythonhosted.org \
    --no-cache-dir -r requirements.txt

COPY services/agent-registry/app/ /app/app/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
