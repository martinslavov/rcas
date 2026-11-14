package com.gbp.rcas.service.impl;

import com.gbp.rcas.model.Subscription;
import com.gbp.rcas.model.User;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.data.redis.core.ReactiveHashOperations;
import org.springframework.data.redis.core.ReactiveRedisTemplate;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MockClock;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.TimeUnit;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import static com.gbp.rcas.config.Constants.CACHE_NAME_SUBSCRIPTION;
import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CacheServiceMetricsTest {

    private static final Duration CACHE_EXPIRATION = Duration.ofHours(24);

    private CacheManager cacheManager;
    private ReactiveHashOperations<String, Long, String> hashOperations;
    private ReactiveRedisTemplate<String, String> redisTemplate;
    private ObjectMapper objectMapper;
    private CacheServiceImpl cacheService;
    private SimpleMeterRegistry meterRegistry;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        cacheManager = new CaffeineCacheManager(CACHE_NAME_USER, CACHE_NAME_SUBSCRIPTION);
        hashOperations = mock(ReactiveHashOperations.class);
        redisTemplate = mock(ReactiveRedisTemplate.class);
        objectMapper = JsonMapper.builder().build();
        meterRegistry = new SimpleMeterRegistry();
        cacheService = new CacheServiceImpl(cacheManager, hashOperations, redisTemplate, objectMapper,
                meterRegistry, 24);
    }

    @Test
    void layerTimersExcludeSynchronousDownstreamWork() throws Exception {
        MockClock clock = new MockClock();
        meterRegistry = new SimpleMeterRegistry(
                io.micrometer.core.instrument.simple.SimpleConfig.DEFAULT, clock);
        cacheService = new CacheServiceImpl(cacheManager, hashOperations, redisTemplate, objectMapper,
                meterRegistry, 24);
        Long id = 41L;
        String redisKey = CACHE_NAME_USER + ":" + id;
        User user = new User.UserBuilder().setId(id).setUsername("timed-user").createUser();
        when(hashOperations.get(redisKey, id)).thenReturn(Mono.empty());
        when(hashOperations.put(redisKey, id, objectMapper.writeValueAsString(user)))
                .thenReturn(Mono.fromSupplier(() -> {
                    clock.add(Duration.ofSeconds(5));
                    return true;
                }));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.fromSupplier(() -> {
            clock.add(Duration.ofSeconds(3));
            return true;
        }));

        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_USER, () -> Mono.fromSupplier(() -> {
            clock.add(Duration.ofSeconds(2));
            return user;
        }), User.class)).expectNext(user).verifyComplete();

        assertEquals(2, meterRegistry.get("rcas.database.read").timer().totalTime(TimeUnit.SECONDS));
        assertEquals(5, meterRegistry.get("rcas.cache.write").tag("layer", "redis")
                .timer().totalTime(TimeUnit.SECONDS));
        assertEquals(3, meterRegistry.get("rcas.cache.ttl.refresh").timer().totalTime(TimeUnit.SECONDS));
        assertEquals(0, meterRegistry.get("rcas.cache.lookup").tag("layer", "caffeine")
                .timer().totalTime(TimeUnit.SECONDS));
        assertEquals(0, meterRegistry.get("rcas.cache.lookup").tag("layer", "redis")
                .timer().totalTime(TimeUnit.SECONDS));
    }

    @Test
    void recordsColdDatabaseReadAndWarmCaffeineReadSeparatelyFromTtlRefresh() throws Exception {
        Long id = 31L;
        String redisKey = CACHE_NAME_USER + ":" + id;
        User user = new User.UserBuilder().setId(id).setUsername("cold-warm-user").createUser();
        when(hashOperations.get(redisKey, id)).thenReturn(Mono.empty());
        when(hashOperations.put(redisKey, id, objectMapper.writeValueAsString(user))).thenReturn(Mono.just(true));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.just(true));
        AtomicInteger databaseCalls = new AtomicInteger();
        Mono<User> result = cacheService.getCache(id, CACHE_NAME_USER, () -> {
            databaseCalls.incrementAndGet();
            return Mono.just(user);
        }, User.class);

        StepVerifier.create(result).expectNext(user).verifyComplete();
        StepVerifier.create(result).expectNext(user).verifyComplete();

        assertEquals(1, databaseCalls.get());
        assertEquals(1, metricCount("rcas.cache.lookup", "layer", "caffeine", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "miss"));
        assertEquals(1, metricCount("rcas.cache.lookup", "layer", "caffeine", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "hit"));
        assertEquals(1, metricCount("rcas.cache.lookup", "layer", "redis", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "miss"));
        assertEquals(1, metricCount("rcas.database.read", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "success"));
        assertEquals(1, metricCount("rcas.cache.ttl.refresh", "cache", CACHE_NAME_USER,
                "operation", "item", "trigger", "caffeine_hit", "outcome", "success"));
        assertEquals(1, metricCount("rcas.cache.ttl.refresh", "cache", CACHE_NAME_USER,
                "operation", "item", "trigger", "write", "outcome", "success"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_USER,
                "operation", "item", "source", "database", "outcome", "success"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_USER,
                "operation", "item", "source", "caffeine", "outcome", "success"));
    }

    @Test
    void redisLookupErrorIsNotAMissAndCountsOnlyAnExecutedDatabaseFallback() throws Exception {
        Long id = 32L;
        String redisKey = CACHE_NAME_USER + ":" + id;
        User user = new User.UserBuilder().setId(id).setUsername("redis-error-user").createUser();
        when(hashOperations.get(redisKey, id)).thenReturn(Mono.error(new IllegalStateException("Redis down")));
        when(hashOperations.put(redisKey, id, objectMapper.writeValueAsString(user)))
                .thenReturn(Mono.just(true));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.just(true));

        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_USER, () -> Mono.just(user), User.class))
                .expectNext(user)
                .verifyComplete();

        assertEquals(1, metricCount("rcas.cache.lookup", "layer", "redis", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "error"));
        assertEquals(0, metricCount("rcas.cache.lookup", "layer", "redis", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "miss"));
        assertEquals(1, meterRegistry.get("rcas.cache.redis.fallback")
                .tags("cache", CACHE_NAME_USER, "operation", "item", "reason", "lookup_error")
                .counter().count());
    }

    @Test
    void recordsRedisHitAsSourceWithoutExecutingDatabaseRead() throws Exception {
        Long id = 40L;
        String redisKey = CACHE_NAME_USER + ":" + id;
        User user = new User.UserBuilder().setId(id).setUsername("redis-hit-user").createUser();
        when(hashOperations.get(redisKey, id)).thenReturn(Mono.just(objectMapper.writeValueAsString(user)));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.just(true));
        AtomicInteger databaseCalls = new AtomicInteger();

        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_USER, () -> {
            databaseCalls.incrementAndGet();
            return Mono.empty();
        }, User.class)).expectNextMatches(value -> value.getId().equals(id)).verifyComplete();

        assertEquals(0, databaseCalls.get());
        assertEquals(1, metricCount("rcas.cache.lookup", "layer", "redis", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "hit"));
        assertEquals(0, metricCount("rcas.database.read", "cache", CACHE_NAME_USER, "operation", "item"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_USER,
                "operation", "item", "source", "redis", "outcome", "success"));
    }

    @Test
    void recordsEmptyListAsOneDatabaseReadAndCachesItAsAnEmptyList() {
        Long id = -25L;
        String redisKey = CACHE_NAME_SUBSCRIPTION + ":" + id;
        when(hashOperations.get(redisKey, id)).thenReturn(Mono.empty());
        when(hashOperations.put(redisKey, id, "[]")).thenReturn(Mono.just(true));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.just(true));

        Flux<Subscription> result = cacheService.getCache(id, CACHE_NAME_SUBSCRIPTION, Subscription.class,
                Flux::empty);
        StepVerifier.create(result).verifyComplete();
        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_SUBSCRIPTION, Subscription.class, Flux::empty))
                .verifyComplete();

        assertEquals(1, metricCount("rcas.database.read", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "outcome", "empty"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "source", "database", "outcome", "empty"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "source", "caffeine", "outcome", "empty"));
        assertEquals(1, metricCount("rcas.cache.lookup", "layer", "caffeine", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "outcome", "hit"));
        verify(hashOperations, times(1)).get(redisKey, id);
    }

    @Test
    void recordsDatabaseErrorsAndListCancellationWithoutFalseSuccessfulLogicalReads() {
        Long id = -26L;
        cacheManager.getCache(CACHE_NAME_SUBSCRIPTION).put(id, List.of(
                new Subscription(1L, "first", 1, 1),
                new Subscription(2L, "second", 1, 1)));
        when(redisTemplate.expire(CACHE_NAME_SUBSCRIPTION + ":" + id, CACHE_EXPIRATION))
                .thenReturn(Mono.just(true));

        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_SUBSCRIPTION, Subscription.class, Flux::empty))
                .thenRequest(1)
                .expectNextMatches(value -> value.getId().equals(1L))
                .thenCancel()
                .verify();

        StepVerifier.create(cacheService.getCache(-27L, CACHE_NAME_SUBSCRIPTION, Subscription.class,
                        () -> Flux.error(new IllegalStateException("repository failure"))))
                .expectError(IllegalStateException.class)
                .verify();

        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "source", "none", "outcome", "cancelled"));
        assertEquals(0, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "source", "caffeine", "outcome", "success"));
        assertEquals(1, metricCount("rcas.database.read", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "outcome", "error"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_SUBSCRIPTION,
                "operation", "list", "source", "none", "outcome", "error"));
    }

    @Test
    void recordsMonoEmptyErrorAndCancellationAsDistinctLogicalOutcomes() {
        Long emptyId = 35L;
        Long errorId = 36L;
        when(hashOperations.get(CACHE_NAME_USER + ":" + emptyId, emptyId)).thenReturn(Mono.empty());
        when(hashOperations.get(CACHE_NAME_USER + ":" + errorId, errorId)).thenReturn(Mono.empty());
        when(hashOperations.get(CACHE_NAME_USER + ":38", 38L)).thenReturn(Mono.never());
        when(hashOperations.get(CACHE_NAME_USER + ":39", 39L)).thenReturn(Mono.empty());

        StepVerifier.create(cacheService.getCache(emptyId, CACHE_NAME_USER, Mono::empty, User.class))
                .verifyComplete();
        StepVerifier.create(cacheService.getCache(errorId, CACHE_NAME_USER,
                        () -> Mono.error(new IllegalStateException("repository failure")), User.class))
                .expectError(IllegalStateException.class)
                .verify();

        Long cancelledId = 37L;
        User user = new User.UserBuilder().setId(cancelledId).setUsername("cancelled-user").createUser();
        cacheManager.getCache(CACHE_NAME_USER).put(cancelledId, user);
        when(redisTemplate.expire(CACHE_NAME_USER + ":" + cancelledId, CACHE_EXPIRATION))
                .thenReturn(Mono.never());
        StepVerifier.create(cacheService.getCache(cancelledId, CACHE_NAME_USER, Mono::empty, User.class), 0)
                .thenRequest(1)
                .expectNoEvent(Duration.ofMillis(10))
                .thenCancel()
                .verify();
        StepVerifier.create(cacheService.getCache(38L, CACHE_NAME_USER, Mono::empty, User.class), 0)
                .thenRequest(1)
                .expectNoEvent(Duration.ofMillis(10))
                .thenCancel()
                .verify();
        StepVerifier.create(cacheService.getCache(39L, CACHE_NAME_USER, () -> Mono.never(), User.class), 0)
                .thenRequest(1)
                .expectNoEvent(Duration.ofMillis(10))
                .thenCancel()
                .verify();
        verify(hashOperations).get(CACHE_NAME_USER + ":38", 38L);

        assertEquals(1, metricCount("rcas.database.read", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "empty"));
        assertEquals(1, metricCount("rcas.database.read", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "error"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_USER,
                "operation", "item", "source", "none", "outcome", "empty"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_USER,
                "operation", "item", "source", "none", "outcome", "error"));
        assertEquals(1, metricCount("rcas.cache.lookup", "layer", "redis", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "cancelled"));
        assertEquals(1, metricCount("rcas.database.read", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "cancelled"));
        assertEquals(3, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_USER,
                "operation", "item", "source", "none", "outcome", "cancelled"));
        assertEquals(1, metricCount("rcas.cache.ttl.refresh", "cache", CACHE_NAME_USER,
                "operation", "item", "trigger", "caffeine_hit", "outcome", "cancelled"));
    }

    @Test
    void recordsSwallowedTtlAndRedisWriteErrors() throws Exception {
        Long id = 33L;
        String redisKey = CACHE_NAME_USER + ":" + id;
        User user = new User.UserBuilder().setId(id).setUsername("write-failure-user").createUser();
        when(hashOperations.get(redisKey, id)).thenReturn(Mono.empty());
        when(hashOperations.put(redisKey, id, objectMapper.writeValueAsString(user)))
                .thenReturn(Mono.error(new IllegalStateException("Redis write failed")));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION))
                .thenReturn(Mono.error(new IllegalStateException("Redis TTL failed")));

        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_USER, () -> Mono.just(user), User.class))
                .expectNext(user)
                .verifyComplete();

        assertEquals(1, metricCount("rcas.cache.write", "layer", "redis", "cache", CACHE_NAME_USER,
                "operation", "item", "outcome", "error"));
        assertEquals(0, metricCount("rcas.cache.ttl.refresh", "cache", CACHE_NAME_USER,
                "operation", "item", "trigger", "write", "outcome", "error"));
        assertEquals(1, metricCount("rcas.cache.logical.read", "cache", CACHE_NAME_USER,
                "operation", "item", "source", "database", "outcome", "success"));

        cacheManager.getCache(CACHE_NAME_USER).put(34L, user);
        StepVerifier.create(cacheService.getCache(34L, CACHE_NAME_USER, Mono::empty, User.class))
                .expectNext(user)
                .verifyComplete();
        assertEquals(1, metricCount("rcas.cache.ttl.refresh", "cache", CACHE_NAME_USER,
                "operation", "item", "trigger", "caffeine_hit", "outcome", "error"));
    }

    private long metricCount(String name, String... tags) {
        Timer timer = meterRegistry.find(name).tags(tags).timer();
        if (timer != null) {
            return timer.count();
        }
        Counter counter = meterRegistry.find(name).tags(tags).counter();
        return counter == null ? 0 : (long) counter.count();
    }
}
