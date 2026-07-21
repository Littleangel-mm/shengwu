# Research Platform API 镜像
# PaddleOCR 模型目录 models/paddleocr 不打进镜像，运行时通过卷挂载到 /srv/app/models。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libgomp1: xgboost / scikit-learn 运行时依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

# 先复制依赖声明与应用包，利用构建缓存
COPY pyproject.toml ./
# requirements.lock 作为版本约束（constraints），复现已测试的依赖版本
COPY requirements.lock ./
COPY app ./app
# alembic 用于容器内执行数据库迁移（pyproject 依赖中未声明）
RUN pip install -c requirements.lock . alembic

# 迁移与运维脚本
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

# 数据与模型目录由卷提供（见 docker-compose.yml）
RUN mkdir -p /srv/app/data /srv/app/models

EXPOSE 8000

# 端口与监听地址由 APP_HOST / APP_PORT 环境变量控制（见 app/core/config.py）
CMD ["python", "-m", "app"]
