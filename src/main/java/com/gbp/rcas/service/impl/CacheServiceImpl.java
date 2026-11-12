package com.gbp.rcas.service.impl;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.data.redis.core.ReactiveHashOperations;
import org.springframework.data.redis.core.ReactiveRedisTemplate;
import org.springframework.stereotype.Service;

import tools.jackson.databind.ObjectMapper;

import java.time.Duration;
import java.util.List;
import java.util.function.Supplier;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import com.gbp.rcas.service.CacheService;

@Service(value = "cacheService")
public class CacheServiceImpl implements CacheService {

    private static final Logger logger = LoggerFactory.getLogger(CacheServiceImpl.class);
    // Separate logger so cache writes can be enabled on demand: logging.level.com.gbp.rcas.cache.write=DEBUG
    private static final Logger WRITE_LOGGER = LoggerFactory.getLogger("com.gbp.rcas.cache.write");
    private static final String CAFFEINE = "Caffeine";
    private static final String REDIS = "Redis";

    private final CacheManager cacheManager;
    private final ReactiveHashOperations<String, Long, String> hashOperations;
    private final ReactiveRedisTemplate<String, String> redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration redisExpiration;

    public CacheServiceImpl(CacheManager cacheManager,
                            ReactiveHashOperations<String, Long, String> hashOperations,
                            @Qualifier("redisCacheTemplate") ReactiveRedisTemplate<String, String> redisTemplate,
                            ObjectMapper objectMapper,
                            @Value("${cache.expiration.hours:24}") long cacheExpirationHours) {
        this.cacheManager = cacheManager;
        this.hashOperations = hashOperations;
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.redisExpiration = Duration.ofHours(cacheExpirationHours);
    }

    @Override
    public <T> Mono<T> getCache(Long id, String cacheName, Supplier<Mono<T>> retriever, Class<T> cls) {
        Cache cache = cacheManager.getCache(cacheName);
        return Mono.defer(() -> {
                    T cached = cache.get(id, cls);
                    logLookup(CAFFEINE, cacheName, id, cached != null);
                    return Mono.justOrEmpty(cached)
                            .flatMap(value -> refreshRedisExpiration(redisKey(cacheName, id)).thenReturn(value));
                })
                .switchIfEmpty(Mono.defer(() -> readFromRedis(id, cacheName, cls)
                        .doOnNext(value -> putInCaffeine(cache, cacheName, id, value))))
                .switchIfEmpty(Mono.defer(() -> {
                    logger.info("{} was not found in any cache (Caffeine, Redis) by id: {}", cls.getName(), id);
                    return retriever.get()
                            .flatMap(value -> writeToRedis(id, cacheName, value)
                                    .thenReturn(value))
                            .doOnNext(value -> putInCaffeine(cache, cacheName, id, value));
                }));
    }

    @Override
    public <T> Flux<T> getCache(Long id, String cacheName, Class<T> cls, Supplier<Flux<T>> retriever) {
        Cache cache = cacheManager.getCache(cacheName);
        return Mono.defer(() -> {
                    Object cachedValue = cache.get(id, Object.class);
                    boolean hit = cachedValue instanceof List<?>;
                    logLookup(CAFFEINE, cacheName, id, hit);
                    if (cachedValue instanceof List<?> values) {
                        return Mono.just(values.stream().map(cls::cast).toList())
                                .flatMap(cachedValues -> refreshRedisExpiration(redisKey(cacheName, id))
                                        .thenReturn(cachedValues));
                    }
                    return Mono.empty();
                })
                .switchIfEmpty(Mono.defer(() -> readListFromRedis(id, cacheName, cls)
                        .doOnNext(values -> putInCaffeine(cache, cacheName, id, values))))
                .switchIfEmpty(Mono.defer(() -> {
                    logger.info("{} was not found in any cache (Caffeine, Redis) by id: {}", cacheName, id);
                    return Flux.defer(retriever).collectList()
                            .flatMap(values -> writeToRedis(id, cacheName, values)
                                    .thenReturn(values))
                            .doOnNext(values -> putInCaffeine(cache, cacheName, id, values));
                }))
                .flatMapMany(Flux::fromIterable);
    }

    private void logLookup(String layer, String cacheName, Long id, boolean hit) {
        logger.info("{} cache {} for {}:{}", layer, hit ? "HIT" : "MISS", cacheName, id);
    }

    private void putInCaffeine(Cache cache, String cacheName, Long id, Object value) {
        cache.put(id, value);
        WRITE_LOGGER.debug("{} cache WRITE for {}:{}", CAFFEINE, cacheName, id);
    }

    private <T> Mono<T> readFromRedis(Long id, String cacheName, Class<T> cls) {
        String redisKey = redisKey(cacheName, id);
        return hashOperations.get(redisKey, id)
                .flatMap(json -> deserialize(json, cls))
                .flatMap(value -> refreshRedisExpiration(redisKey).thenReturn(value))
                .doOnNext(value -> logLookup(REDIS, cacheName, id, true))
                .switchIfEmpty(Mono.fromRunnable(() -> logLookup(REDIS, cacheName, id, false)))
                .onErrorResume(error -> {
                    logger.warn("Redis cache lookup failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private <T> Mono<List<T>> readListFromRedis(Long id, String cacheName, Class<T> cls) {
        String redisKey = redisKey(cacheName, id);
        return hashOperations.get(redisKey, id)
                .flatMap(json -> deserializeList(json, cls))
                .flatMap(values -> refreshRedisExpiration(redisKey).thenReturn(values))
                .doOnNext(values -> logLookup(REDIS, cacheName, id, true))
                .switchIfEmpty(Mono.fromRunnable(() -> logLookup(REDIS, cacheName, id, false)))
                .onErrorResume(error -> {
                    logger.warn("Redis cache lookup failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private Mono<Void> writeToRedis(Long id, String cacheName, Object value) {
        String redisKey = redisKey(cacheName, id);
        return serialize(value)
                .flatMap(json -> hashOperations.put(redisKey, id, json))
                .then(refreshRedisExpiration(redisKey))
                .doOnSuccess(ignored -> WRITE_LOGGER.debug("{} cache WRITE for {}", REDIS, redisKey))
                .onErrorResume(error -> {
                    logger.warn("Redis cache write failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private String redisKey(String cacheName, Long id) {
        return cacheName + ":" + id;
    }

    private Mono<Void> refreshRedisExpiration(String redisKey) {
        return redisTemplate.expire(redisKey, redisExpiration)
                .then()
                .onErrorResume(error -> {
                    logger.warn("Redis cache expiration update failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private <T> Mono<String> serialize(T value) {
        return Mono.fromCallable(() -> objectMapper.writeValueAsString(value));
    }

    private <T> Mono<T> deserialize(String json, Class<T> cls) {
        return Mono.fromCallable(() -> objectMapper.readValue(json, cls));
    }

    private <T> Mono<List<T>> deserializeList(String json, Class<T> cls) {
        var listType = objectMapper.getTypeFactory().constructCollectionType(List.class, cls);
        return Mono.fromCallable(() -> objectMapper.readValue(json, listType));
    }
}
