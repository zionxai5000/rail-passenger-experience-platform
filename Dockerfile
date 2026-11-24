FROM python:3.12-slim
WORKDIR /app
COPY rpx ./rpx
COPY tests ./tests
RUN python -m unittest discover -s tests
CMD ["python", "-m", "rpx.demo"]
