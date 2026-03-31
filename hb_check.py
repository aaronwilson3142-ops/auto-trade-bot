import redis, os
r = redis.Redis.from_url(os.environ.get('APIS_REDIS_URL','redis://redis:6379/0'), socket_connect_timeout=2)
print('ping:', r.ping())
print('heartbeat_exists:', r.exists('worker:heartbeat'))
print('worker_keys:', r.keys('worker:*'))
print('ttl:', r.ttl('worker:heartbeat'))
