package com.gbp.rcas.service.impl;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.data.redis.core.ReactiveHashOperations;
import org.springframework.data.redis.core.ReactiveRedisTemplate;
import org.springframework.stereotype.Service;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import tools.jackson.databind.ObjectMapper;

import java.time.Duration;
import java.time.Clock;
import java.util.List;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.Predicate;
import java.util.function.Supplier;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.SignalType;

import com.gbp.rcas.service.CacheService;
import com.gbp.rcas.config.CachePolicy;

import static com.gbp.rcas.config.Constants.CACHE_NAME_SUBSCRIPTION;
import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;

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
    private final Duration redisExpiration;
    private final Duration maxLifetime;
    private final Clock clock;
    private final CacheMetrics metrics;
    private final CacheKeyCoordinator keyCoordinator;
    private final CacheEntryCodec cacheEntryCodec;
    private final RedisCacheReader redisCacheReader;

    public CacheServiceImpl(CacheManager cacheManager,
                            ReactiveHashOperations<String, Long, String> hashOperations,
                            @Qualifier("redisCacheTemplate") ReactiveRedisTemplate<String, String> redisTemplate,
                            ObjectMapper objectMapper,
                            MeterRegistry meterRegistry,
                            CachePolicy cachePolicy) {
        this.cacheManager = cacheManager;
        this.hashOperations = hashOperations;
        this.redisTemplate = redisTemplate;
        this.redisExpiration = cachePolicy.redisExpiration();
        this.maxLifetime = cachePolicy.maxLifetime();
        this.clock = cachePolicy.clock();
        this.metrics = new CacheMetrics(meterRegistry);
        this.keyCoordinator = new CacheKeyCoordinator(cacheManager, redisTemplate);
        this.cacheEntryCodec = new CacheEntryCodec(objectMapper);
        this.redisCacheReader = new RedisCacheReader(hashOperations, cacheEntryCodec, keyCoordinator);
    }

    @Override
    public <T> Mono<T> getCache(Long id, String cacheName, Supplier<Mono<T>> retriever, Class<T> cls) {
        Cache cache = cacheManager.getCache(cacheName);
        String redisKey = redisKey(cacheName, id);
        return measureLogicalRead(cacheName, OPERATION_ITEM, redisKey, context ->
                Mono.defer(() -> {
                            return lookupCaffeine(cacheName, OPERATION_ITEM, id,
                                            () -> cache.get(id, CacheEntry.class),
                                            entry -> isFreshCaffeineEntry(cache, id, entry, context))
                                    .flatMap(entry -> refreshRedisExpiration(
                                                    redisKey, cacheName, OPERATION_ITEM, "caffeine_hit",
                                                    entry.cachedAtEpochMillis(), context)
                                            .thenReturn(cls.cast(entry.value())))
                                    .doOnNext(value -> context.source = SOURCE_CAFFEINE);
                        })
                        .switchIfEmpty(Mono.defer(() -> readFromRedis(id, cacheName, cls, OPERATION_ITEM, context)
                                .flatMap(entry -> putInCaffeine(cache, cacheName, id, entry, context)
                                        .thenReturn(cls.cast(entry.value())))
                                .doOnNext(value -> context.source = SOURCE_REDIS)))
                        .switchIfEmpty(Mono.defer(() -> {
                            logger.info("{} was not found in any cache (Caffeine, Redis) by id: {}",
                                    cls.getName(), id);
                            return readDatabase(cacheName, OPERATION_ITEM, context, retriever, value -> false)
                                    .flatMap(value -> cacheDatabaseValue(
                                            cache, id, cacheName, value, OPERATION_ITEM, context).thenReturn(value))
                                    .doOnNext(value -> context.source = SOURCE_DATABASE);
                        })));
    }

    @Override
    public <T> Flux<T> getCache(Long id, String cacheName, Class<T> cls, Supplier<Flux<T>> retriever) {
        Cache cache = cacheManager.getCache(cacheName);
        String redisKey = redisKey(cacheName, id);
        return measureLogicalListRead(cacheName, OPERATION_LIST, redisKey, context ->
                Mono.defer(() -> {
                            return lookupCaffeine(cacheName, OPERATION_LIST, id,
                                            () -> cache.get(id, CacheEntry.class),
                                            entry -> isFreshCaffeineEntry(cache, id, entry, context))
                                    .flatMap(entry -> {
                                        List<?> values = (List<?>) entry.value();
                                        List<T> typedValues = values.stream().map(cls::cast).toList();
                                        return refreshRedisExpiration(
                                                redisKey, cacheName, OPERATION_LIST, "caffeine_hit",
                                                entry.cachedAtEpochMillis(), context)
                                                .thenReturn(typedValues)
                                                .doOnNext(ignored -> context.source = SOURCE_CAFFEINE);
                                    });
                        })
                        .switchIfEmpty(Mono.defer(() -> readListFromRedis(
                                id, cacheName, cls, OPERATION_LIST, context)
                                .flatMap(entry -> putInCaffeine(cache, cacheName, id, entry, context)
                                        .thenReturn(((List<?>) entry.value()).stream().map(cls::cast).toList()))
                                .doOnNext(values -> context.source = SOURCE_REDIS)))
                        .switchIfEmpty(Mono.defer(() -> {
                            logger.info("{} was not found in any cache (Caffeine, Redis) by id: {}",
                                    cacheName, id);
                            return readDatabaseList(cacheName, OPERATION_LIST, context, retriever)
                                    .flatMap(values -> cacheDatabaseValue(
                                            cache, id, cacheName, values, OPERATION_LIST, context).thenReturn(values))
                                    .doOnNext(values -> context.source = SOURCE_DATABASE);
                        })));
    }

    @Override
    public Mono<Void> invalidateUser(Long userId) {
        return Mono.defer(() -> keyCoordinator.invalidate(List.of(
                new CacheKeyCoordinator.CacheKey(CACHE_NAME_USER, userId))));
    }

    @Override
    public Mono<Void> invalidateSubscription(Long subscriptionId, Long oldUserId, Long newUserId) {
        return Mono.defer(() -> {
            LinkedHashSet<CacheKeyCoordinator.CacheKey> affected = new LinkedHashSet<>();
            affected.add(new CacheKeyCoordinator.CacheKey(CACHE_NAME_SUBSCRIPTION, subscriptionId));
            if (oldUserId != null) {
                affected.add(new CacheKeyCoordinator.CacheKey(
                        CACHE_NAME_SUBSCRIPTION, Math.negateExact(oldUserId)));
            }
            if (newUserId != null) {
                affected.add(new CacheKeyCoordinator.CacheKey(
                        CACHE_NAME_SUBSCRIPTION, Math.negateExact(newUserId)));
            }
            return keyCoordinator.invalidate(new ArrayList<>(affected));
        });
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

    private Mono<Void> cacheDatabaseValue(Cache cache, Long id, String cacheName, Object value,
                                          String operation, ReadContext context) {
        return Mono.defer(() -> {
            CacheEntry entry = new CacheEntry(clock.millis(), value);
            return writeToRedis(id, cacheName, entry, operation, context)
                    .then(putInCaffeine(cache, cacheName, id, entry, context));
        });
    }

    private boolean isFreshCaffeineEntry(Cache cache, Long id, CacheEntry entry, ReadContext context) {
        if (entry == null) {
            return false;
        }
        if (isFresh(entry.cachedAtEpochMillis())) {
            return true;
        }
        keyCoordinator.evictIfSame(context.token, cache, id, entry);
        return false;
    }

    private Mono<Void> putInCaffeine(Cache cache, String cacheName, Long id,
                                     CacheEntry entry, ReadContext context) {
        return Mono.<Void>defer(() -> {
            Timer.Sample sample = metrics.start();
            return Mono.<Void>fromRunnable(() -> {
                if (keyCoordinator.putIfCurrent(context.token, cache, id, entry)) {
                    WRITE_LOGGER.debug("{} cache WRITE for {}:{}", CAFFEINE, cacheName, id);
                }
                    })
                    .transform(result -> recordCompletion(result, signal -> metrics.recordCacheWrite(
                            sample, "caffeine", cacheName, operationFor(entry.value()), operationOutcome(signal))));
        });
    }

    private <T> Mono<CacheEntry> readFromRedis(Long id, String cacheName, Class<T> cls,
                                               String operation, ReadContext context) {
        String redisKey = redisKey(cacheName, id);
        return measureReactiveLookup("redis", cacheName, operation,
                        () -> redisCacheReader.readItem(redisKey, id, cls)
                                .flatMap(entry -> isFresh(entry.cachedAtEpochMillis())
                                        ? Mono.just(entry)
                                        : keyCoordinator.deleteRedisKey(redisKey).then(Mono.empty())))
                .doOnNext(entry -> logLookup(REDIS, cacheName, id, true))
                .switchIfEmpty(Mono.defer(() -> {
                    logLookup(REDIS, cacheName, id, false);
                    return Mono.empty();
                }))
                .doOnError(error -> context.redisLookupFailed = true)
                .flatMap(entry -> {
                    return refreshRedisExpiration(redisKey, cacheName, operation, "redis_hit",
                            entry.cachedAtEpochMillis(), context).thenReturn(entry);
                })
                .onErrorResume(error -> {
                    logger.warn("Redis cache lookup failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private <T> Mono<CacheEntry> readListFromRedis(Long id, String cacheName, Class<T> cls,
                                                   String operation, ReadContext context) {
        String redisKey = redisKey(cacheName, id);
        return measureReactiveLookup("redis", cacheName, operation,
                        () -> redisCacheReader.readList(redisKey, id, cls)
                                .flatMap(entry -> isFresh(entry.cachedAtEpochMillis())
                                        ? Mono.just(entry)
                                        : keyCoordinator.deleteRedisKey(redisKey).then(Mono.empty())))
                .doOnNext(entry -> logLookup(REDIS, cacheName, id, true))
                .switchIfEmpty(Mono.defer(() -> {
                    logLookup(REDIS, cacheName, id, false);
                    return Mono.empty();
                }))
                .doOnError(error -> context.redisLookupFailed = true)
                .flatMap(entry -> {
                    return refreshRedisExpiration(redisKey, cacheName, operation, "redis_hit",
                            entry.cachedAtEpochMillis(), context).thenReturn(entry);
                })
                .onErrorResume(error -> {
                    logger.warn("Redis cache lookup failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private Mono<Void> writeToRedis(Long id, String cacheName, CacheEntry entry,
                                    String operation, ReadContext context) {
        String redisKey = redisKey(cacheName, id);
        return measureReactiveWrite("redis", cacheName, operation, () ->
                        cacheEntryCodec.encode(entry)
                                .flatMap(json -> keyCoordinator.enqueueRedis(redisKey, context.token, false, () ->
                                        Mono.defer(() -> hashOperations.put(redisKey, id, json)).then())))
                .then(Mono.defer(() -> refreshRedisExpiration(redisKey, cacheName, operation, "write",
                        entry.cachedAtEpochMillis(), context)))
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

    private Mono<Void> refreshRedisExpiration(String redisKey, String cacheName, String operation, String trigger,
                                               long cachedAtEpochMillis, ReadContext context) {
        return keyCoordinator.enqueueRedis(redisKey, context.token, false, () ->
                refreshRedisExpirationDirect(redisKey, cacheName, operation, trigger, cachedAtEpochMillis));
    }

    private Mono<Void> refreshRedisExpirationDirect(String redisKey, String cacheName, String operation,
                                                     String trigger, long cachedAtEpochMillis) {
        Duration ttl = remainingLifetime(cachedAtEpochMillis);
        if (ttl.isZero() || ttl.isNegative()) {
            return Mono.empty();
        }
        Duration effectiveTtl = ttl.compareTo(redisExpiration) > 0 ? redisExpiration : ttl;
        return Mono.defer(() -> {
                    Timer.Sample sample = metrics.start();
                    return Mono.defer(() -> redisTemplate.expire(redisKey, effectiveTtl))
                            .then()
                            .transform(result -> recordCompletion(result, signal -> metrics.recordTtlRefresh(
                                    sample, cacheName, operation, trigger, operationOutcome(signal))));
                })
                .onErrorResume(error -> {
                    logger.warn("Redis cache expiration update failed for {}", redisKey, error);
                    return Mono.empty();
                });
    }

    private Duration remainingLifetime(long cachedAtEpochMillis) {
        long ageMillis = clock.millis() - cachedAtEpochMillis;
        long remainingMillis = maxLifetime.toMillis() - ageMillis;
        return Duration.ofMillis(Math.max(0, remainingMillis));
    }

    private boolean isFresh(long cachedAtEpochMillis) {
        long ageMillis = clock.millis() - cachedAtEpochMillis;
        return ageMillis >= 0 && ageMillis < maxLifetime.toMillis();
    }

    private <T> Mono<T> measureLogicalRead(String cacheName, String operation, String redisKey,
                                            Function<ReadContext, Mono<T>> read) {
        return Mono.defer(() -> {
            ReadContext context = new ReadContext(keyCoordinator.begin(redisKey));
            AtomicBoolean hasValue = new AtomicBoolean();
            return read.apply(context)
                    .doOnNext(ignored -> hasValue.set(true))
                    .doOnError(ignored -> context.source = SOURCE_NONE)
                    .doFinally(signal -> {
                        try {
                            String outcome = logicalOutcome(signal, hasValue.get());
                            String source = signal == SignalType.ON_COMPLETE && hasValue.get()
                                    ? context.source : SOURCE_NONE;
                            metrics.recordLogicalRead(cacheName, operation, source, outcome);
                        } finally {
                            keyCoordinator.release(context.token);
                        }
                    });
        });
    }

    private <T> Flux<T> measureLogicalListRead(String cacheName, String operation, String redisKey,
                                                Function<ReadContext, Mono<List<T>>> read) {
        return Flux.defer(() -> {
            ReadContext context = new ReadContext(keyCoordinator.begin(redisKey));
            AtomicBoolean emptyResult = new AtomicBoolean();
            return read.apply(context)
                    .flatMapMany(values -> {
                        emptyResult.set(values.isEmpty());
                        return Flux.fromIterable(values);
                    })
                    .doOnError(ignored -> context.source = SOURCE_NONE)
                    .doFinally(signal -> {
                        try {
                            String outcome = signal == SignalType.ON_COMPLETE
                                    ? emptyResult.get() ? "empty" : "success"
                                    : signal == SignalType.ON_ERROR ? "error" : "cancelled";
                            String source = signal == SignalType.ON_COMPLETE ? context.source : SOURCE_NONE;
                            metrics.recordLogicalRead(cacheName, operation, source, outcome);
                        } finally {
                            keyCoordinator.release(context.token);
                        }
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
        private final CacheKeyCoordinator.KeyToken token;
        private String source = SOURCE_NONE;
        private boolean redisLookupFailed;

        private ReadContext(CacheKeyCoordinator.KeyToken token) {
            this.token = token;
        }
    }

}
