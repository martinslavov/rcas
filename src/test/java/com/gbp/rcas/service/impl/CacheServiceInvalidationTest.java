package com.gbp.rcas.service.impl;

import com.gbp.rcas.config.CachePolicy;
import com.gbp.rcas.model.Subscription;
import com.gbp.rcas.model.User;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.data.redis.core.ReactiveHashOperations;
import org.springframework.data.redis.core.ReactiveRedisTemplate;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;
import reactor.test.StepVerifier;

import static com.gbp.rcas.config.Constants.CACHE_NAME_SUBSCRIPTION;
import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

class CacheServiceInvalidationTest {

    private CacheManager cacheManager;
    private ReactiveHashOperations<String, Long, String> hashOperations;
    private ReactiveRedisTemplate<String, String> redisTemplate;
    private ObjectMapper objectMapper;
    private CacheServiceImpl cacheService;
    private Clock clock;
    private Map<String, String> redisValues;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        cacheManager = new CaffeineCacheManager(CACHE_NAME_USER, CACHE_NAME_SUBSCRIPTION);
        hashOperations = mock(ReactiveHashOperations.class);
        redisTemplate = mock(ReactiveRedisTemplate.class);
        objectMapper = JsonMapper.builder().build();
        clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);
        cacheService = new CacheServiceImpl(cacheManager, hashOperations, redisTemplate, objectMapper,
                new SimpleMeterRegistry(), new CachePolicy(Duration.ofHours(24), Duration.ofHours(24), clock));
    }

    @Test
    void invalidatesUserAcrossBothTiersAndPreservesUnrelatedUser() throws Exception {
        useInMemoryRedis();
        long changedId = 51L;
        long unrelatedId = 52L;
        User stale = new User.UserBuilder().setId(changedId).setUsername("stale-user").createUser();
        User unrelated = new User.UserBuilder().setId(unrelatedId).setUsername("unrelated-user").createUser();
        cacheManager.getCache(CACHE_NAME_USER).put(changedId, new CacheEntry(clock.millis(), stale));
        cacheManager.getCache(CACHE_NAME_USER).put(unrelatedId, new CacheEntry(clock.millis(), unrelated));
        redisValues.put(CACHE_NAME_USER + ":" + changedId, cacheJson(stale));
        redisValues.put(CACHE_NAME_USER + ":" + unrelatedId, cacheJson(unrelated));

        StepVerifier.create(cacheService.invalidateUser(changedId)).verifyComplete();

        AtomicInteger sourceCalls = new AtomicInteger();
        User current = new User.UserBuilder().setId(changedId).setUsername("current-user").createUser();
        StepVerifier.create(cacheService.getCache(changedId, CACHE_NAME_USER, () -> {
            sourceCalls.incrementAndGet();
            return Mono.just(current);
        }, User.class)).expectNext(current).verifyComplete();
        StepVerifier.create(cacheService.getCache(unrelatedId, CACHE_NAME_USER, () -> {
            sourceCalls.incrementAndGet();
            return Mono.empty();
        }, User.class)).expectNext(unrelated).verifyComplete();

        assertEquals(1, sourceCalls.get());
        assertEquals(cacheJson(current), redisValues.get(CACHE_NAME_USER + ":" + changedId));
        assertEquals(cacheJson(unrelated), redisValues.get(CACHE_NAME_USER + ":" + unrelatedId));
        verify(redisTemplate).delete(CACHE_NAME_USER + ":" + changedId);
        verify(redisTemplate, org.mockito.Mockito.never()).delete(CACHE_NAME_USER + ":" + unrelatedId);
    }

    @Test
    void replacesLegacyRedisPayloadsInsteadOfTreatingThemAsFresh() throws Exception {
        useInMemoryRedis();
        Long id = 55L;
        User legacy = new User.UserBuilder().setId(id).setUsername("legacy").createUser();
        User current = new User.UserBuilder().setId(id).setUsername("current").createUser();
        redisValues.put(CACHE_NAME_USER + ":" + id, objectMapper.writeValueAsString(legacy));

        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_USER, () -> Mono.just(current), User.class))
                .expectNext(current).verifyComplete();

        assertEquals(cacheJson(current), redisValues.get(CACHE_NAME_USER + ":" + id));
        verify(redisTemplate).delete(CACHE_NAME_USER + ":" + id);
    }

    @Test
    void invalidatesSubscriptionItemAndOldAndNewListsIncludingEmptyList() throws Exception {
        useInMemoryRedis();
        Subscription oldSubscription = new Subscription(61L, "old", 1, 1);
        Subscription unrelatedSubscription = new Subscription(62L, "unrelated", 1, 1);
        cacheEntries(CACHE_NAME_SUBSCRIPTION,
                Map.of(61L, oldSubscription, -6L, List.of(oldSubscription), -7L, List.of(),
                        62L, unrelatedSubscription, -8L, List.of(unrelatedSubscription)));

        StepVerifier.create(cacheService.invalidateSubscription(61L, 6L, 7L)).verifyComplete();

        for (Long key : List.of(61L, -6L, -7L)) {
            assertNull(cacheManager.getCache(CACHE_NAME_SUBSCRIPTION).get(key));
            assertNull(redisValues.get(CACHE_NAME_SUBSCRIPTION + ":" + key));
            verify(redisTemplate).delete(CACHE_NAME_SUBSCRIPTION + ":" + key);
        }
        Subscription currentSubscription = new Subscription(61L, "current", 1, 1);
        AtomicInteger sourceCalls = new AtomicInteger();
        StepVerifier.create(cacheService.getCache(61L, CACHE_NAME_SUBSCRIPTION, () -> {
            sourceCalls.incrementAndGet();
            return Mono.just(currentSubscription);
        }, Subscription.class)).expectNext(currentSubscription).verifyComplete();
        StepVerifier.create(cacheService.getCache(-6L, CACHE_NAME_SUBSCRIPTION, Subscription.class, () -> {
            sourceCalls.incrementAndGet();
            return Flux.empty();
        })).verifyComplete();
        StepVerifier.create(cacheService.getCache(-7L, CACHE_NAME_SUBSCRIPTION, Subscription.class, () -> {
            sourceCalls.incrementAndGet();
            return Flux.just(currentSubscription);
        })).expectNext(currentSubscription).verifyComplete();

        assertEquals(3, sourceCalls.get());
        assertEquals(unrelatedSubscription,
                ((CacheEntry) cacheManager.getCache(CACHE_NAME_SUBSCRIPTION).get(62L).get()).value());
        assertEquals(List.of(unrelatedSubscription),
                ((CacheEntry) cacheManager.getCache(CACHE_NAME_SUBSCRIPTION).get(-8L).get()).value());
        assertEquals(cacheJson(unrelatedSubscription), redisValues.get(CACHE_NAME_SUBSCRIPTION + ":62"));
        assertEquals(cacheJson(List.of(unrelatedSubscription)), redisValues.get(CACHE_NAME_SUBSCRIPTION + ":-8"));
        verify(redisTemplate, org.mockito.Mockito.never()).delete(CACHE_NAME_SUBSCRIPTION + ":62");
        verify(redisTemplate, org.mockito.Mockito.never()).delete(CACHE_NAME_SUBSCRIPTION + ":-8");
    }

    @Test
    void maxLifetimeExpiresPromotedUserItemAndListWithoutRenewingOnHits() throws Exception {
        MutableClock mutableClock = new MutableClock(Instant.parse("2026-01-01T00:00:00Z"));
        cacheService = new CacheServiceImpl(cacheManager, hashOperations, redisTemplate, objectMapper,
                new SimpleMeterRegistry(), new CachePolicy(Duration.ofHours(24), Duration.ofHours(1), mutableClock));
        useInMemoryRedis();
        User cachedUser = new User.UserBuilder().setId(71L).setUsername("cached-user").createUser();
        Subscription cachedItem = new Subscription(72L, "cached-item", 1, 1);
        Subscription cachedListItem = new Subscription(73L, "cached-list", 1, 1);
        redisValues.put(CACHE_NAME_USER + ":71", cacheJson(cachedUser, mutableClock.millis()));
        redisValues.put(CACHE_NAME_SUBSCRIPTION + ":72", cacheJson(cachedItem, mutableClock.millis()));
        redisValues.put(CACHE_NAME_SUBSCRIPTION + ":-73",
                cacheJson(List.of(cachedListItem), mutableClock.millis()));
        AtomicInteger databaseCalls = new AtomicInteger();

        Mono<User> userRead = cacheService.getCache(71L, CACHE_NAME_USER, () -> {
            databaseCalls.incrementAndGet();
            return Mono.just(new User.UserBuilder().setId(71L).setUsername("fresh-user").createUser());
        }, User.class);
        Mono<Subscription> itemRead = cacheService.getCache(72L, CACHE_NAME_SUBSCRIPTION, () -> {
            databaseCalls.incrementAndGet();
            return Mono.just(new Subscription(72L, "fresh-item", 1, 1));
        }, Subscription.class);
        Flux<Subscription> listRead = cacheService.getCache(-73L, CACHE_NAME_SUBSCRIPTION, Subscription.class, () -> {
            databaseCalls.incrementAndGet();
            return Flux.just(new Subscription(73L, "fresh-list", 1, 1));
        });

        expectReads(userRead, itemRead, listRead, "cached-user", "cached-item", "cached-list");
        mutableClock.advance(Duration.ofMinutes(10));
        expectReads(userRead, itemRead, listRead, "cached-user", "cached-item", "cached-list");
        verify(redisTemplate, times(3)).expire(org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.eq(Duration.ofMinutes(50)));

        mutableClock.advance(Duration.ofMinutes(40));
        cacheManager.getCache(CACHE_NAME_USER).evict(71L);
        cacheManager.getCache(CACHE_NAME_SUBSCRIPTION).evict(72L);
        cacheManager.getCache(CACHE_NAME_SUBSCRIPTION).evict(-73L);
        expectReads(userRead, itemRead, listRead, "cached-user", "cached-item", "cached-list");
        verify(redisTemplate, times(3)).expire(org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.eq(Duration.ofMinutes(10)));

        mutableClock.advance(Duration.ofMinutes(11));
        expectReads(userRead, itemRead, listRead, "fresh-user", "fresh-item", "fresh-list");
        assertEquals(3, databaseCalls.get());
    }

    private void expectReads(Mono<User> userRead, Mono<Subscription> itemRead, Flux<Subscription> listRead,
                             String username, String itemType, String listType) {
        StepVerifier.create(userRead).expectNextMatches(value -> value.getUsername().equals(username))
                .verifyComplete();
        StepVerifier.create(itemRead).expectNextMatches(value -> value.getType().equals(itemType))
                .verifyComplete();
        StepVerifier.create(listRead).expectNextMatches(value -> value.getType().equals(listType))
                .verifyComplete();
    }

    @Test
    void invalidationFailureIsObservableAndMissingKeysAreSafe() {
        User cached = new User.UserBuilder().setId(81L).setUsername("cached").createUser();
        cacheManager.getCache(CACHE_NAME_USER).put(81L, new CacheEntry(clock.millis(), cached));
        org.mockito.Mockito.when(redisTemplate.delete(CACHE_NAME_USER + ":81"))
                .thenReturn(Mono.error(new IllegalStateException("Redis unavailable")));

        StepVerifier.create(cacheService.invalidateUser(81L))
                .expectErrorMatches(error -> error instanceof IllegalStateException
                        && error.getMessage().equals("Redis unavailable"))
                .verify();
        assertNull(cacheManager.getCache(CACHE_NAME_USER).get(81L));

        org.mockito.Mockito.when(redisTemplate.delete(CACHE_NAME_USER + ":82")).thenReturn(Mono.just(0L));
        StepVerifier.create(cacheService.invalidateUser(82L)).verifyComplete();
    }

    @Test
    void inFlightPreInvalidationReadCannotRepopulateEitherTier() throws Exception {
        useInMemoryRedis();
        Long id = 91L;
        User stale = new User.UserBuilder().setId(id).setUsername("stale").createUser();
        User current = new User.UserBuilder().setId(id).setUsername("current").createUser();
        Sinks.One<User> databaseResult = Sinks.one();
        Sinks.One<User> firstResult = Sinks.one();
        cacheService.getCache(id, CACHE_NAME_USER, databaseResult::asMono, User.class)
                .subscribe(firstResult::tryEmitValue);
        StepVerifier.create(cacheService.invalidateUser(id)).verifyComplete();
        databaseResult.tryEmitValue(stale);
        StepVerifier.create(firstResult.asMono()).expectNext(stale).verifyComplete();
        assertNull(cacheManager.getCache(CACHE_NAME_USER).get(id));
        assertNull(redisValues.get(CACHE_NAME_USER + ":" + id));

        StepVerifier.create(cacheService.getCache(id, CACHE_NAME_USER, () -> Mono.just(current), User.class))
                .expectNext(current).verifyComplete();
        assertEquals(cacheJson(current), redisValues.get(CACHE_NAME_USER + ":" + id));
    }

    private void useInMemoryRedis() {
        redisValues = new ConcurrentHashMap<>();
        org.mockito.Mockito.when(hashOperations.get(org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyLong())).thenAnswer(invocation ->
                Mono.justOrEmpty(redisValues.get(invocation.getArgument(0))));
        org.mockito.Mockito.when(hashOperations.put(org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyLong(), org.mockito.ArgumentMatchers.anyString()))
                .thenAnswer(invocation -> {
                    redisValues.put(invocation.getArgument(0), invocation.getArgument(2));
                    return Mono.just(true);
                });
        org.mockito.Mockito.when(redisTemplate.delete(org.mockito.ArgumentMatchers.anyString()))
                .thenAnswer(invocation -> Mono.just(redisValues.remove(invocation.getArgument(0)) == null ? 0L : 1L));
        org.mockito.Mockito.when(redisTemplate.expire(org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any(Duration.class))).thenReturn(Mono.just(true));
    }

    private void cacheEntries(String cacheName, Map<Long, Object> values) throws Exception {
        for (Map.Entry<Long, Object> entry : values.entrySet()) {
            cacheManager.getCache(cacheName).put(entry.getKey(), new CacheEntry(clock.millis(), entry.getValue()));
            redisValues.put(cacheName + ":" + entry.getKey(), cacheJson(entry.getValue()));
        }
    }

    private String cacheJson(Object value, long cachedAtEpochMillis) throws Exception {
        return objectMapper.writeValueAsString(new CacheEntryEnvelope(cachedAtEpochMillis,
                objectMapper.writeValueAsString(value)));
    }

    private String cacheJson(Object value) throws Exception {
        return cacheJson(value, clock.millis());
    }

    private static final class MutableClock extends Clock {
        private final AtomicReference<Instant> current;

        private MutableClock(Instant initial) {
            this.current = new AtomicReference<>(initial);
        }

        private void advance(Duration duration) {
            current.updateAndGet(instant -> instant.plus(duration));
        }

        @Override
        public java.time.ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return current.get();
        }
    }
}
