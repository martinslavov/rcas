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

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import tools.jackson.databind.ObjectMapper;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.Predicate;
import java.util.function.Supplier;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.SignalType;

import com.gbp.rcas.service.CacheService;

@Service(value = "cacheService")
public class CacheServiceImpl implements CacheService {

    private static final Logger logger = LoggerFactory.getLogger(CacheServiceImpl.class);
    // Separate logger so cache writes can be enabled on demand: logging.level.com.gbp.rcas.cache.write=DEBUG
    private static final Logger WRITE_LOGGER = LoggerFactory.getLogger("com.gbp.rcas.cache.write");
    private static final String CAFFEINE = "Caffeine";
    private static final String REDIS = "Redis";
    private static final String OPERATION_ITEM = "item";
    private static final String OPERATION_LIST = "list";
    private static final String SOURCE_CAFFEINE = "caffeine";
    private static final String SOURCE_REDIS = "redis";
    private static final String SOURCE_DATABASE = "database";
    private static final String SOURCE_NONE = "none";

    private final CacheManager cacheManager;
    private final ReactiveHashOperations<String, Long, String> hashOperations;
    private final ReactiveRedisTemplate<String, String> redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration redisExpiration;
    private final CacheMetrics metrics;

    public CacheServiceImpl(CacheManager cacheManager,
                            ReactiveHashOperations<String, Long, String> hashOperations,
                            @Qualifier("redisCacheTemplate") ReactiveRedisTemplate<String, String> redisTemplate,
                            ObjectMapper objectMapper,
                            MeterRegistry meterRegistry,
                            @Value("${cache.expiration.hours:24}") long cacheExpirationHours) {
        this.cacheManager = cacheManager;
        this.hashOperations = hashOperations;
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.redisExpiration = Duration.ofHours(cacheExpirationHours);
        this.metrics = new CacheMetrics(meterRegistry);
    }

    @Override
    public <T> Mono<T> getCache(Long id, String cacheName, Supplier<Mono<T>> retriever, Class<T> cls) {
        Cache cache = cacheManager.getCache(cacheName);
        return measureLogicalRead(cacheName, OPERATION_ITEM, context ->
                Mono.defer(() -> {
                            return lookupCaffeine(cacheName, OPERATION_ITEM, id, () -> cache.get(id, cls),
                                            value -> true)
                                    .flatMap(value -> refreshRedisExpiration(
                                            redisKey(cacheName, id), cacheName, OPERATION_ITEM, "caffeine_hit")
                                            .thenReturn(value))
                                    .doOnNext(value -> context.source = SOURCE_CAFFEINE);
                        })
                        .switchIfEmpty(Mono.defer(() -> readFromRedis(
                                id, cacheName, cls, OPERATION_ITEM, context)
                                .flatMap(value -> putInCaffeine(cache, cacheName, id, value).thenReturn(value))
                                .doOnNext(value -> context.source = SOURCE_REDIS)))
                        .switchIfEmpty(Mono.defer(() -> {
                            logger.info("{} was not found in any cache (Caffeine, Redis) by id: {}",
                                    cls.getName(), id);
                            return readDatabase(cacheName, OPERATION_ITEM, context, retriever, value -> false)
                                    .flatMap(value -> writeToRedis(
                                            id, cacheName, value, OPERATION_ITEM).thenReturn(value))
                                    .flatMap(value -> putInCaffeine(cache, cacheName, id, value).thenReturn(value))
                                    .doOnNext(value -> context.source = SOURCE_DATABASE);
                        })));
    }

    @Override
    public <T> Flux<T> getCache(Long id, String cacheName, Class<T> cls, Supplier<Flux<T>> retriever) {
        Cache cache = cacheManager.getCache(cacheName);
        return measureLogicalListRead(cacheName, OPERATION_LIST, context ->
                Mono.defer(() -> {
                            return lookupCaffeine(cacheName, OPERATION_LIST, id,
                                            () -> cache.get(id, Object.class), value -> value instanceof List<?>)
                                    .flatMap(cachedValue -> {
                                        List<?> values = (List<?>) cachedValue;
                                        List<T> typedValues = values.stream().map(cls::cast).toList();
                                        return refreshRedisExpiration(
                                                redisKey(cacheName, id), cacheName, OPERATION_LIST, "caffeine_hit")
                                                .thenReturn(typedValues)
                                                .doOnNext(ignored -> context.source = SOURCE_CAFFEINE);
                                    });
                        })
                        .switchIfEmpty(Mono.defer(() -> readListFromRedis(
                                id, cacheName, cls, OPERATION_LIST, context)
                                .flatMap(values -> putInCaffeine(cache, cacheName, id, values).thenReturn(values))
                                .doOnNext(values -> context.source = SOURCE_REDIS)))
                        .switchIfEmpty(Mono.defer(() -> {
                            logger.info("{} was not found in any cache (Caffeine, Redis) by id: {}",
                                    cacheName, id);
                            return readDatabaseList(cacheName, OPERATION_LIST, context, retriever)
                                    .flatMap(values -> writeToRedis(
                                            id, cacheName, values, OPERATION_LIST).thenReturn(values))
                                    .flatMap(values -> putInCaffeine(cache, cacheName, id, values).thenReturn(values))
                                    .doOnNext(values -> context.source = SOURCE_DATABASE);
                        })));
    }

    private void logLookup(String layer, String cacheName, Long id, boolean hit) {
        logger.info("{} cache {} for {}:{}", layer, hit ? "HIT" : "MISS", cacheName, id);
    }

    private <T> Mono<T> lookupCaffeine(String cacheName, String operation, Long id,
                                       Supplier<T> lookup, Predicate<T> isHit) {
        return Mono.defer(() -> {
            Timer.Sample sample = metrics.start();
            AtomicBoolean hasValue = new AtomicBoolean();
            return Mono.fromCallable(lookup::get)
                    .doOnSuccess(value -> {
                        if (value == null) {
                            logLookup(CAFFEINE, cacheName, id, false);
                        }
                    })
                    .flatMap(value -> {
                        boolean hit = isHit.test(value);
                        if (hit) {
                            logLookup(CAFFEINE, cacheName, id, true);
                            hasValue.set(true);
                            return Mono.just(value);
                        }
                        logLookup(CAFFEINE, cacheName, id, false);
                        return Mono.empty();
                    })
                    .transform(result -> recordCompletion(result, signal -> metrics.recordLookup(
                            sample, "caffeine", cacheName, operation, cacheOutcome(signal, hasValue.get()))));
        });
    }

    private <T> Mono<T> measureReactiveLookup(String layer, String cacheName, String operation,
                                               Supplier<Mono<T>> lookup) {
        return Mono.defer(() -> {
            Timer.Sample sample = metrics.start();
            AtomicBoolean hasValue = new AtomicBoolean();
            return Mono.defer(lookup)
                    .doOnNext(ignored -> hasValue.set(true))
                    .transform(result -> recordCompletion(result, signal -> metrics.recordLookup(
                            sample, layer, cacheName, operation, cacheOutcome(signal, hasValue.get()))));
        });
    }

    private <T> Mono<T> measureDatabaseRead(String cacheName, String operation, ReadContext context,
                                             Supplier<Mono<T>> retriever, Predicate<T> isEmpty) {
        return Mono.defer(() -> {
            Timer.Sample sample = metrics.start();
            AtomicBoolean hasValue = new AtomicBoolean();
            AtomicBoolean emptyResult = new AtomicBoolean();
            return Mono.defer(() -> {
                        if (context.redisLookupFailed) {
                            metrics.recordRedisFallback(cacheName, operation);
                        }
                        return retriever.get();
                    })
                    .doOnNext(value -> {
                        hasValue.set(true);
                        emptyResult.set(isEmpty.test(value));
                    })
                    .doOnSuccess(value -> {
                        if (value == null) {
                            emptyResult.set(true);
                        }
                    })
                    .transform(result -> recordCompletion(result, signal -> {
                        String outcome = signal == SignalType.ON_ERROR ? "error"
                                : signal == SignalType.CANCEL ? "cancelled"
                                : !hasValue.get() || emptyResult.get() ? "empty" : "success";
                        metrics.recordDatabaseRead(sample, cacheName, operation, outcome);
                    }));
        });
    }

    private <T> Mono<T> readDatabase(String cacheName, String operation, ReadContext context,
                                     Supplier<Mono<T>> retriever, Predicate<T> isEmpty) {
        return measureDatabaseRead(cacheName, operation, context, retriever, isEmpty)
                .doOnNext(ignored -> context.source = SOURCE_DATABASE);
    }

    private <T> Mono<List<T>> readDatabaseList(String cacheName, String operation, ReadContext context,
                                               Supplier<Flux<T>> retriever) {
        return measureDatabaseRead(cacheName, operation, context,
                        () -> Flux.defer(retriever).collectList(), List::isEmpty)
                .doOnNext(ignored -> context.source = SOURCE_DATABASE);
    }

    private Mono<Void> putInCaffeine(Cache cache, String cacheName, Long id, Object value) {
        return Mono.<Void>defer(() -> {
            Timer.Sample sample = metrics.start();
            return Mono.<Void>fromRunnable(() -> {
                        cache.put(id, value);
                        WRITE_LOGGER.debug("{} cache WRITE for {}:{}", CAFFEINE, cacheName, id);
                    })
                    .transform(result -> recordCompletion(result, signal -> metrics.recordCacheWrite(
                            sample, "caffeine", cacheName, operationFor(value), operationOutcome(signal))));
        });
    }

    private <T> Mono<T> readFromRedis(Long id, String cacheName, Class<T> cls,
                                      String operation, ReadContext context) {
        String redisKey = redisKey(cacheName, id);
        return measureReactiveLookup("redis", cacheName, operation, () ->
                        Mono.defer(() -> hashOperations.get(redisKey, id))
                                .flatMap(json -> deserialize(json, cls)))
                .doOnNext(value -> logLookup(REDIS, cacheName, id, true))
                .switchIfEmpty(Mono.defer(() -> {
                    logLookup(REDIS, cacheName, id, false);
                    return Mono.empty();
                }))
                .doOnError(error -> context.redisLookupFailed = true)
                .flatMap(value -> refreshRedisExpiration(redisKey, cacheName, operation, "redis_hit")
                        .thenReturn(value))
                .onErrorResume(error -> {
                    logger.warn("Redis cache lookup failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private <T> Mono<List<T>> readListFromRedis(Long id, String cacheName, Class<T> cls,
                                                String operation, ReadContext context) {
        String redisKey = redisKey(cacheName, id);
        return measureReactiveLookup("redis", cacheName, operation, () ->
                        Mono.defer(() -> hashOperations.get(redisKey, id))
                                .flatMap(json -> deserializeList(json, cls)))
                .doOnNext(values -> logLookup(REDIS, cacheName, id, true))
                .switchIfEmpty(Mono.defer(() -> {
                    logLookup(REDIS, cacheName, id, false);
                    return Mono.empty();
                }))
                .doOnError(error -> context.redisLookupFailed = true)
                .flatMap(values -> refreshRedisExpiration(redisKey, cacheName, operation, "redis_hit")
                        .thenReturn(values))
                .onErrorResume(error -> {
                    logger.warn("Redis cache lookup failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private Mono<Void> writeToRedis(Long id, String cacheName, Object value, String operation) {
        String redisKey = redisKey(cacheName, id);
        return measureReactiveWrite("redis", cacheName, operation, () ->
                        Mono.defer(() -> serialize(value))
                                .flatMap(json -> Mono.defer(() -> hashOperations.put(redisKey, id, json)))
                                .then())
                .then(Mono.defer(() -> refreshRedisExpiration(redisKey, cacheName, operation, "write")))
                .doOnSuccess(ignored -> WRITE_LOGGER.debug("{} cache WRITE for {}", REDIS, redisKey))
                .onErrorResume(error -> {
                    logger.warn("Redis cache write failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private Mono<Void> measureReactiveWrite(String layer, String cacheName, String operation,
                                            Supplier<Mono<Void>> write) {
        return Mono.defer(() -> {
            Timer.Sample sample = metrics.start();
            return Mono.defer(write)
                    .transform(result -> recordCompletion(result, signal -> metrics.recordCacheWrite(
                            sample, layer, cacheName, operation, operationOutcome(signal))));
        });
    }

    private String redisKey(String cacheName, Long id) {
        return cacheName + ":" + id;
    }

    private Mono<Void> refreshRedisExpiration(String redisKey, String cacheName, String operation, String trigger) {
        return Mono.defer(() -> {
                    Timer.Sample sample = metrics.start();
                    return Mono.defer(() -> redisTemplate.expire(redisKey, redisExpiration))
                            .then()
                            .transform(result -> recordCompletion(result, signal -> metrics.recordTtlRefresh(
                                    sample, cacheName, operation, trigger, operationOutcome(signal))));
                })
                .onErrorResume(error -> {
                    logger.warn("Redis cache expiration update failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private <T> Mono<T> measureLogicalRead(String cacheName, String operation,
                                            Function<ReadContext, Mono<T>> read) {
        return Mono.defer(() -> {
            ReadContext context = new ReadContext();
            AtomicBoolean hasValue = new AtomicBoolean();
            return read.apply(context)
                    .doOnNext(ignored -> hasValue.set(true))
                    .doOnError(ignored -> context.source = SOURCE_NONE)
                    .doFinally(signal -> {
                        String outcome = logicalOutcome(signal, hasValue.get());
                        String source = signal == SignalType.ON_COMPLETE && hasValue.get()
                                ? context.source : SOURCE_NONE;
                        metrics.recordLogicalRead(cacheName, operation, source, outcome);
                    });
        });
    }

    private <T> Flux<T> measureLogicalListRead(String cacheName, String operation,
                                                Function<ReadContext, Mono<List<T>>> read) {
        return Flux.defer(() -> {
            ReadContext context = new ReadContext();
            AtomicBoolean emptyResult = new AtomicBoolean();
            return read.apply(context)
                    .flatMapMany(values -> {
                        emptyResult.set(values.isEmpty());
                        return Flux.fromIterable(values);
                    })
                    .doOnError(ignored -> context.source = SOURCE_NONE)
                    .doFinally(signal -> {
                        String outcome = signal == SignalType.ON_COMPLETE
                                ? emptyResult.get() ? "empty" : "success"
                                : signal == SignalType.ON_ERROR ? "error" : "cancelled";
                        String source = signal == SignalType.ON_COMPLETE ? context.source : SOURCE_NONE;
                        metrics.recordLogicalRead(cacheName, operation, source, outcome);
                    });
        });
    }

    private String cacheOutcome(SignalType signal, boolean hasValue) {
        return signal == SignalType.ON_ERROR ? "error"
                : signal == SignalType.CANCEL ? "cancelled"
                : hasValue ? "hit" : "miss";
    }

    private String operationOutcome(SignalType signal) {
        return signal == SignalType.ON_ERROR ? "error"
                : signal == SignalType.CANCEL ? "cancelled" : "success";
    }

    private String logicalOutcome(SignalType signal, boolean hasValue) {
        return signal == SignalType.ON_ERROR ? "error"
                : signal == SignalType.CANCEL ? "cancelled"
                : hasValue ? "success" : "empty";
    }

    private String operationFor(Object value) {
        return value instanceof List<?> ? OPERATION_LIST : OPERATION_ITEM;
    }

    private <T> Mono<T> recordCompletion(Mono<T> operation, Consumer<SignalType> record) {
        return Mono.defer(() -> {
            AtomicBoolean recorded = new AtomicBoolean();
            Consumer<SignalType> once = signal -> {
                if (recorded.compareAndSet(false, true)) {
                    record.accept(signal);
                }
            };
            // Stop before propagating signals: synchronous downstream work belongs to the next layer.
            return operation.doOnSuccess(ignored -> once.accept(SignalType.ON_COMPLETE))
                    .doOnError(ignored -> once.accept(SignalType.ON_ERROR))
                    .doOnCancel(() -> once.accept(SignalType.CANCEL));
        });
    }

    private static final class ReadContext {
        private String source = SOURCE_NONE;
        private boolean redisLookupFailed;
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
