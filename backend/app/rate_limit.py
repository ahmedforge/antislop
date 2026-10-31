"""Atomic Redis token buckets shared by reports and appeals."""
from hashlib import sha256
from ipaddress import ip_address
from math import ceil

from fastapi import HTTPException, Request
from redis import Redis
from redis.exceptions import RedisError

from app.config import Settings
from app.schemas import Submission

# Redis TIME is shared by all workers. Check both buckets before consuming either.
# Rejections do not create keys for arbitrary new installation IDs.
TOKEN_BUCKET = """
local time = redis.call('TIME')
local now = tonumber(time[1]) + tonumber(time[2]) / 1000000
local tokens = {}
local updated = {}
local retry = 0
for i, key in ipairs(KEYS) do
    local capacity = tonumber(ARGV[(i - 1) * 2 + 1])
    local seconds = tonumber(ARGV[(i - 1) * 2 + 2])
    local state = redis.call('HMGET', key, 'tokens', 'updated')
    local previous = tonumber(state[2]) or now
    tokens[i] = math.min(capacity, (tonumber(state[1]) or capacity) + math.max(0, now - previous) / seconds)
    updated[i] = math.max(now, previous)
    if tokens[i] < 1 then
        retry = math.max(retry, (1 - tokens[i]) * seconds)
    end
end
if retry > 0 then
    return {0, math.max(1, math.ceil(retry))}
end
for i, key in ipairs(KEYS) do
    local capacity = tonumber(ARGV[(i - 1) * 2 + 1])
    local seconds = tonumber(ARGV[(i - 1) * 2 + 2])
    redis.call('HSET', key, 'tokens', tokens[i] - 1, 'updated', updated[i])
    redis.call('PEXPIRE', key, math.ceil(capacity * seconds * 1000))
end
return {1, 0}
"""


def bucket_keys(settings: Settings, install_id: str, peer: str) -> tuple[str, str]:
    # Normalize IPv6 spelling and IPv4-mapped IPv6 to avoid separate quotas.
    try:
        address = ip_address(peer)
        peer = str(getattr(address, "ipv4_mapped", None) or address)
    except ValueError:
        pass  # ASGI test transports may use a non-IP peer name.
    prefix = f"{settings.rate_limit_namespace}:{{submissions}}"
    return (f"{prefix}:install:{install_id}", f"{prefix}:ip:{sha256(peer.encode()).hexdigest()}")


def consume(redis: Redis, settings: Settings, install_id: str, peer: str) -> int:
    keys = bucket_keys(settings, install_id, peer)
    allowed, retry = redis.eval(
        TOKEN_BUCKET, len(keys), *keys,
        settings.rate_limit_install_capacity, settings.rate_limit_install_refill_seconds,
        settings.rate_limit_ip_capacity, settings.rate_limit_ip_refill_seconds,
    )
    return 0 if allowed else max(1, ceil(float(retry)))


def enforce_submission_limits(payload: Submission, request: Request) -> None:
    # Trust the ASGI socket peer, not arbitrary Forwarded/X-Forwarded-For headers.
    peer = request.client.host if request.client else "unknown"
    try:
        retry = consume(request.app.state.redis, request.app.state.settings, str(payload.install_id), peer)
    except RedisError:
        raise HTTPException(503, "Submission protection temporarily unavailable; please retry.",
                            headers={"Retry-After": "5", "Cache-Control": "no-store"}) from None
    if retry:
        raise HTTPException(429, "Too many submissions; please retry later.",
                            headers={"Retry-After": str(retry), "Cache-Control": "no-store"})
