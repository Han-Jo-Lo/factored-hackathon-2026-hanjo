from celery import Celery
from config import REDIS_BROKER,REDIS_BACKEND

app_celery=Celery(
    'worker',
    broker=REDIS_BROKER,
    backend=REDIS_BACKEND,
    include=['tasks']
)
