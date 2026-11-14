package com.gbp.rcas.service.impl;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.ReactiveHashOperations;

import reactor.core.publisher.Mono;

final class RedisCacheReader {

    private static final Logger logger = LoggerFactory.getLogger(RedisCacheReader.class);

    private final ReactiveHashOperations<String, Long, String> hashOperations;
    private final CacheEntryCodec codec;
    private final CacheKeyCoordinator keyCoordinator;

    RedisCacheReader(ReactiveHashOperations<String, Long, String> hashOperations,
                     CacheEntryCodec codec, CacheKeyCoordinator keyCoordinator) {
        this.hashOperations = hashOperations;
        this.codec = codec;
        this.keyCoordinator = keyCoordinator;
    }

    <T> Mono<CacheEntry> readItem(String redisKey, Long id, Class<T> cls) {
        return Mono.defer(() -> hashOperations.get(redisKey, id))
                .flatMap(json -> codec.decodeItem(json, cls)
                        .onErrorResume(error -> handleMalformedEntry(redisKey, error)));
    }

    <T> Mono<CacheEntry> readList(String redisKey, Long id, Class<T> cls) {
        return Mono.defer(() -> hashOperations.get(redisKey, id))
                .flatMap(json -> codec.decodeList(json, cls)
                        .onErrorResume(error -> handleMalformedEntry(redisKey, error)));
    }

    private Mono<CacheEntry> handleMalformedEntry(String redisKey, Throwable error) {
        logger.info("Ignoring legacy or malformed cache value for {}", redisKey, error);
        return keyCoordinator.deleteRedisKey(redisKey).then(Mono.empty());
    }
}
