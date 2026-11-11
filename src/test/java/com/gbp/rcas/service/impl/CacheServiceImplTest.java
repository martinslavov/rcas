package com.gbp.rcas.service.impl;

import com.gbp.rcas.model.Subscription;
import com.gbp.rcas.model.User;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.data.redis.core.ReactiveHashOperations;
import org.springframework.data.redis.core.ReactiveRedisTemplate;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

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

class CacheServiceImplTest {

    private static final Duration CACHE_EXPIRATION = Duration.ofHours(24);

    private CacheManager cacheManager;
    private ReactiveHashOperations<String, Long, String> hashOperations;
    private ReactiveRedisTemplate<String, String> redisTemplate;
    private ObjectMapper objectMapper;
    private CacheServiceImpl cacheService;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        cacheManager = new CaffeineCacheManager(CACHE_NAME_USER, CACHE_NAME_SUBSCRIPTION);
        hashOperations = mock(ReactiveHashOperations.class);
        redisTemplate = mock(ReactiveRedisTemplate.class);
        objectMapper = JsonMapper.builder().build();
        cacheService = new CacheServiceImpl(cacheManager, hashOperations, redisTemplate, objectMapper, 24);
    }

    @Test
    void refreshesRedisExpirationOnL1HitWithoutReadingRedisOrDatabase() {
        User user = new User.UserBuilder().setId(1L).setUsername("cached-user").createUser();
        String redisKey = CACHE_NAME_USER + ":1";
        cacheManager.getCache(CACHE_NAME_USER).put(1L, user);
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.just(true));
        AtomicInteger databaseCalls = new AtomicInteger();

        Mono<User> result = cacheService.getCache(1L, CACHE_NAME_USER, () -> {
            databaseCalls.incrementAndGet();
            return Mono.empty();
        }, User.class);

        StepVerifier.create(result).expectNext(user).verifyComplete();
        StepVerifier.create(result).expectNext(user).verifyComplete();

        assertEquals(0, databaseCalls.get());
        verify(hashOperations, times(0)).get(redisKey, 1L);
        verify(redisTemplate, times(2)).expire(redisKey, CACHE_EXPIRATION);
    }

    @Test
    void refreshesRedisExpirationOnSubscriptionListL1HitWithoutReadingRedisOrDatabase() {
        Long id = -1L;
        String redisKey = CACHE_NAME_SUBSCRIPTION + ":" + id;
        Subscription subscription = new Subscription(4L, "premium", 1, 1);
        cacheManager.getCache(CACHE_NAME_SUBSCRIPTION).put(id, List.of(subscription));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.just(true));
        AtomicInteger databaseCalls = new AtomicInteger();

        Flux<Subscription> result = cacheService.getCache(id, CACHE_NAME_SUBSCRIPTION, Subscription.class, () -> {
            databaseCalls.incrementAndGet();
            return Flux.empty();
        });

        StepVerifier.create(result).expectNext(subscription).verifyComplete();
        StepVerifier.create(result).expectNext(subscription).verifyComplete();

        assertEquals(0, databaseCalls.get());
        verify(hashOperations, times(0)).get(redisKey, id);
        verify(redisTemplate, times(2)).expire(redisKey, CACHE_EXPIRATION);
    }

    @Test
    void promotesRedisHitToL1() throws Exception {
        User user = new User.UserBuilder().setId(2L).setUsername("redis-user").createUser();
        when(hashOperations.get(CACHE_NAME_USER + ":2", 2L))
                .thenReturn(Mono.just(objectMapper.writeValueAsString(user)));
        when(redisTemplate.expire(CACHE_NAME_USER + ":2", CACHE_EXPIRATION)).thenReturn(Mono.just(true));

        Mono<User> firstRead = cacheService.getCache(2L, CACHE_NAME_USER, Mono::empty, User.class);
        Mono<User> secondRead = cacheService.getCache(2L, CACHE_NAME_USER, Mono::empty, User.class);

        StepVerifier.create(firstRead)
                .expectNextMatches(value -> value.getId().equals(user.getId()))
                .verifyComplete();
        StepVerifier.create(secondRead)
                .expectNextMatches(value -> value.getId().equals(user.getId()))
                .verifyComplete();

        verify(hashOperations, times(1)).get(CACHE_NAME_USER + ":2", 2L);
        verify(redisTemplate, times(2)).expire(CACHE_NAME_USER + ":2", CACHE_EXPIRATION);
    }

    @Test
    void storesDatabaseResultInRedisAndL1() throws Exception {
        User user = new User.UserBuilder().setId(3L).setUsername("database-user").createUser();
        AtomicInteger databaseCalls = new AtomicInteger();
        when(hashOperations.get(CACHE_NAME_USER + ":3", 3L)).thenReturn(Mono.empty());
        when(hashOperations.put(CACHE_NAME_USER + ":3", 3L, objectMapper.writeValueAsString(user)))
                .thenReturn(Mono.just(true));
        when(redisTemplate.expire(CACHE_NAME_USER + ":3", CACHE_EXPIRATION)).thenReturn(Mono.just(true));

        Mono<User> firstRead = cacheService.getCache(3L, CACHE_NAME_USER, () -> {
            databaseCalls.incrementAndGet();
            return Mono.just(user);
        }, User.class);
        Mono<User> secondRead = cacheService.getCache(3L, CACHE_NAME_USER, () -> {
            databaseCalls.incrementAndGet();
            return Mono.just(user);
        }, User.class);

        StepVerifier.create(firstRead).expectNext(user).verifyComplete();
        StepVerifier.create(secondRead).expectNext(user).verifyComplete();

        assertEquals(1, databaseCalls.get());
        verify(hashOperations).put(CACHE_NAME_USER + ":3", 3L, objectMapper.writeValueAsString(user));
    }

    @Test
    void cachesSubscriptionListsAsJsonUsingElementClass() throws Exception {
        Subscription subscription = new Subscription(4L, "premium", 1, 1);
        List<Subscription> subscriptions = List.of(subscription);
        AtomicInteger databaseCalls = new AtomicInteger();
        when(hashOperations.get(CACHE_NAME_SUBSCRIPTION + ":-1", -1L)).thenReturn(Mono.empty());
        when(hashOperations.put(CACHE_NAME_SUBSCRIPTION + ":-1", -1L,
                objectMapper.writeValueAsString(subscriptions))).thenReturn(Mono.just(true));
        when(redisTemplate.expire(CACHE_NAME_SUBSCRIPTION + ":-1", CACHE_EXPIRATION)).thenReturn(Mono.just(true));

        Flux<Subscription> firstRead = cacheService.getCache(-1L, CACHE_NAME_SUBSCRIPTION, Subscription.class, () -> {
            databaseCalls.incrementAndGet();
            return Flux.fromIterable(subscriptions);
        });
        Flux<Subscription> secondRead = cacheService.getCache(-1L, CACHE_NAME_SUBSCRIPTION, Subscription.class,
                Flux::empty);

        StepVerifier.create(firstRead).expectNext(subscription).verifyComplete();
        StepVerifier.create(secondRead).expectNext(subscription).verifyComplete();

        assertEquals(1, databaseCalls.get());
        verify(hashOperations).put(CACHE_NAME_SUBSCRIPTION + ":-1", -1L,
                objectMapper.writeValueAsString(subscriptions));
    }

    @Test
    void deserializesSubscriptionListFromRedisUsingElementClass() throws Exception {
        Subscription subscription = new Subscription(6L, "standard", 1, 2);
        String redisKey = CACHE_NAME_SUBSCRIPTION + ":-2";
        when(hashOperations.get(redisKey, -2L))
                .thenReturn(Mono.just(objectMapper.writeValueAsString(List.of(subscription))));
        when(redisTemplate.expire(redisKey, CACHE_EXPIRATION)).thenReturn(Mono.just(true));

        Flux<Subscription> result = cacheService.getCache(-2L, CACHE_NAME_SUBSCRIPTION, Subscription.class,
                Flux::empty);

        StepVerifier.create(result)
                .expectNextMatches(value -> value.getId().equals(subscription.getId())
                        && value.getType().equals(subscription.getType()))
                .verifyComplete();
    }

    @Test
    void fallsBackToDatabaseWhenRedisIsUnavailable() {
        User user = new User.UserBuilder().setId(5L).setUsername("fallback-user").createUser();
        when(hashOperations.get(CACHE_NAME_USER + ":5", 5L))
                .thenReturn(Mono.error(new IllegalStateException("Redis down")));
        when(hashOperations.put(CACHE_NAME_USER + ":5", 5L, objectMapper.writeValueAsString(user)))
                .thenReturn(Mono.just(true));
        when(redisTemplate.expire(CACHE_NAME_USER + ":5", CACHE_EXPIRATION)).thenReturn(Mono.just(true));

        Mono<User> result = cacheService.getCache(5L, CACHE_NAME_USER, () -> Mono.just(user), User.class);

        StepVerifier.create(result).expectNext(user).verifyComplete();
    }
}
