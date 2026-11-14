package com.gbp.rcas.service.impl;

import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.data.redis.core.ReactiveRedisTemplate;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;

final class CacheKeyCoordinator {

    private final CacheManager cacheManager;
    private final ReactiveRedisTemplate<String, String> redisTemplate;
    private final Map<String, KeyState> keyStates = new ConcurrentHashMap<>();

    CacheKeyCoordinator(CacheManager cacheManager, ReactiveRedisTemplate<String, String> redisTemplate) {
        this.cacheManager = cacheManager;
        this.redisTemplate = redisTemplate;
    }

    KeyToken begin(String redisKey) {
        AtomicReference<KeyToken> token = new AtomicReference<>();
        keyStates.compute(redisKey, (key, current) -> {
            KeyState state = current == null ? new KeyState() : current;
            synchronized (state) {
                state.readers++;
                token.set(new KeyToken(redisKey, state, state.generation));
            }
            return state;
        });
        return token.get();
    }

    void release(KeyToken token) {
        keyStates.computeIfPresent(token.redisKey, (key, current) -> {
            if (current != token.state) {
                return current;
            }
            synchronized (current) {
                current.readers--;
                return current.readers == 0 && current.pendingRedisOperations == 0 ? null : current;
            }
        });
    }

    void evictIfSame(KeyToken token, Cache cache, Long id, CacheEntry entry) {
        synchronized (token.state) {
            if (cache.get(id, CacheEntry.class) == entry) {
                cache.evictIfPresent(id);
            }
        }
    }

    boolean putIfCurrent(KeyToken token, Cache cache, Long id, CacheEntry entry) {
        synchronized (token.state) {
            if (token.state.generation == token.generation) {
                cache.put(id, entry);
                return true;
            }
            return false;
        }
    }

    Mono<Void> invalidate(List<CacheKey> keys) {
        return Mono.defer(() -> {
            for (CacheKey key : keys) {
                String redisKey = redisKey(key.cacheName(), key.id());
                keyStates.compute(redisKey, (keyName, current) -> {
                    KeyState state = current == null ? new KeyState() : current;
                    synchronized (state) {
                        state.generation++;
                        Cache cache = cacheManager.getCache(key.cacheName());
                        if (cache != null) {
                            cache.evictIfPresent(key.id());
                        }
                    }
                    return state;
                });
            }
            return Flux.fromIterable(keys)
                    .concatMap(key -> deleteRedisKey(redisKey(key.cacheName(), key.id())))
                    .then();
        });
    }

    Mono<Void> deleteRedisKey(String redisKey) {
        return enqueueRedis(redisKey, null, true, () -> Mono.defer(() -> redisTemplate.delete(redisKey)).then());
    }

    Mono<Void> enqueueRedis(String redisKey, KeyToken token, boolean force, Supplier<Mono<Void>> operation) {
        AtomicReference<Mono<Void>> queuedResult = new AtomicReference<>();
        keyStates.compute(redisKey, (key, current) -> {
            KeyState state = current == null ? new KeyState() : current;
            synchronized (state) {
                state.pendingRedisOperations++;
                Sinks.One<Void> completion = Sinks.one();
                Mono<Void> queued = state.redisTail.then(Mono.defer(() -> {
                    if (!force && token != null) {
                        synchronized (state) {
                            if (state.generation != token.generation) {
                                return Mono.empty();
                            }
                        }
                    }
                    return operation.get();
                })).doFinally(ignored -> {
                    completion.tryEmitEmpty();
                    releaseRedisOperation(redisKey, state);
                });
                state.redisTail = completion.asMono();
                queuedResult.set(queued);
            }
            return state;
        });
        return queuedResult.get();
    }

    private void releaseRedisOperation(String redisKey, KeyState state) {
        keyStates.computeIfPresent(redisKey, (key, current) -> {
            if (current != state) {
                return current;
            }
            synchronized (current) {
                current.pendingRedisOperations--;
                return current.readers == 0 && current.pendingRedisOperations == 0 ? null : current;
            }
        });
    }

    private String redisKey(String cacheName, Long id) {
        return cacheName + ":" + id;
    }

    record CacheKey(String cacheName, Long id) {
    }

    static final class KeyToken {
        private final String redisKey;
        private final KeyState state;
        private final long generation;

        private KeyToken(String redisKey, KeyState state, long generation) {
            this.redisKey = redisKey;
            this.state = state;
            this.generation = generation;
        }
    }

    private static final class KeyState {
        private long generation;
        private int readers;
        private int pendingRedisOperations;
        private Mono<Void> redisTail = Mono.empty();
    }
}
