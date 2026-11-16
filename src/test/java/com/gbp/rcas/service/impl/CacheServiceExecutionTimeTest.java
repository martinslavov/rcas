package com.gbp.rcas.service.impl;

import org.apache.logging.log4j.Level;
import org.apache.logging.log4j.core.LogEvent;
import org.apache.logging.log4j.core.LoggerContext;
import org.apache.logging.log4j.core.appender.AbstractAppender;
import org.apache.logging.log4j.core.config.Configuration;
import org.apache.logging.log4j.core.config.LoggerConfig;
import com.gbp.rcas.aop.ExecutionTimeAspect;
import com.gbp.rcas.model.User;
import com.gbp.rcas.service.CacheService;

import io.micrometer.core.instrument.Meter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.aop.support.AopUtils;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.EnableAspectJAutoProxy;
import org.springframework.data.redis.core.ReactiveHashOperations;
import org.springframework.data.redis.core.ReactiveRedisTemplate;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CacheServiceExecutionTimeTest {

    private static final Pattern TIMING =
            Pattern.compile("^CacheServiceImpl\\.getCache executed in (\\d+) ms \\((\\w+)\\)$");
    private static final long ID = 7L;
    private static final String REDIS_KEY = CACHE_NAME_USER + ":" + ID;

    private ReactiveHashOperations<String, Long, String> hashOperations;
    private ReactiveRedisTemplate<String, String> redisTemplate;
    private SimpleMeterRegistry meterRegistry;
    private AnnotationConfigApplicationContext context;
    private CacheService cacheService;
    private LoggerConfig loggerConfig;
    private CapturingAppender appender;

    @EnableAspectJAutoProxy(proxyTargetClass = true)
    static class AopConfig {
    }

    static class CapturingAppender extends AbstractAppender {
        private final List<LogEvent> events = new CopyOnWriteArrayList<>();

        CapturingAppender() {
            super("execution-time-capture", null, null, true, org.apache.logging.log4j.core.config.Property.EMPTY_ARRAY);
        }

        @Override
        public void append(LogEvent event) {
            events.add(event.toImmutable());
        }
    }

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        hashOperations = mock(ReactiveHashOperations.class);
        redisTemplate = mock(ReactiveRedisTemplate.class);
        meterRegistry = new SimpleMeterRegistry();
        when(hashOperations.get(anyString(), anyLong())).thenReturn(Mono.empty());
        when(hashOperations.put(anyString(), anyLong(), anyString())).thenReturn(Mono.just(true));
        when(redisTemplate.expire(anyString(), any(Duration.class))).thenReturn(Mono.just(true));

        context = new AnnotationConfigApplicationContext();
        context.register(AopConfig.class);
        context.registerBean(ExecutionTimeAspect.class);
        context.registerBean(CacheServiceImpl.class, () -> newService(meterRegistry));
        context.refresh();
        cacheService = context.getBean(CacheService.class);
        assertTrue(AopUtils.isAopProxy(cacheService));

        LoggerContext loggerContext = (LoggerContext) org.apache.logging.log4j.LogManager.getContext(false);
        Configuration configuration = loggerContext.getConfiguration();
        appender = new CapturingAppender();
        appender.start();
        loggerConfig = new LoggerConfig(ExecutionTimeAspect.class.getName(), Level.INFO, false);
        loggerConfig.addAppender(appender, Level.INFO, null);
        configuration.addLogger(ExecutionTimeAspect.class.getName(), loggerConfig);
        loggerContext.updateLoggers();
    }

    @AfterEach
    void tearDown() {
        LoggerContext loggerContext = (LoggerContext) org.apache.logging.log4j.LogManager.getContext(false);
        loggerContext.getConfiguration().removeLogger(ExecutionTimeAspect.class.getName());
        loggerContext.updateLoggers();
        appender.stop();
        context.close();
    }

    private CacheServiceImpl newService(SimpleMeterRegistry registry) {
        CacheManager cacheManager = new CaffeineCacheManager(CACHE_NAME_USER);
        ObjectMapper objectMapper = JsonMapper.builder().build();
        return new CacheServiceImpl(cacheManager, hashOperations, redisTemplate, objectMapper, registry, 24);
    }

    private List<LogEvent> timings() {
        return List.copyOf(appender.events);
    }

    // doFinally runs after the downstream terminal signal, so the log may land just after verify() returns
    private List<LogEvent> awaitTimings(int expected) throws InterruptedException {
        long deadline = System.nanoTime() + Duration.ofSeconds(2).toNanos();
        while (appender.events.size() < expected && System.nanoTime() < deadline) {
            Thread.sleep(5);
        }
        Thread.sleep(20);
        return timings();
    }

    private Matcher timing(LogEvent event) {
        Matcher matcher = TIMING.matcher(event.getMessage().getFormattedMessage());
        assertTrue(matcher.matches(), event.getMessage().getFormattedMessage());
        assertEquals(Level.INFO, event.getLevel());
        return matcher;
    }

    private User user(long id) {
        return new User.UserBuilder().setId(id).setUsername("u" + id).createUser();
    }

    @Test
    void monoReadLogsNothingUntilSubscribedThenOneTimingEntryIncludingAsyncWork() throws InterruptedException {
        AtomicInteger retrievals = new AtomicInteger();
        User user = user(ID);

        Mono<User> result = cacheService.getCache(ID, CACHE_NAME_USER, () -> {
            retrievals.incrementAndGet();
            return Mono.delay(Duration.ofMillis(150)).thenReturn(user);
        }, User.class);

        assertTrue(timings().isEmpty());
        StepVerifier.create(result).expectNext(user).verifyComplete();

        assertEquals(1, awaitTimings(1).size());
        Matcher matcher = timing(awaitTimings(1).get(0));
        assertTrue(Long.parseLong(matcher.group(1)) >= 140);
        assertEquals("success", matcher.group(2));
        assertEquals(1, retrievals.get());
    }

    @Test
    void fluxReadLogsNothingUntilSubscribedThenOneTimingEntryIncludingAsyncWork() throws InterruptedException {
        AtomicInteger retrievals = new AtomicInteger();
        User first = user(1);
        User second = user(2);

        Flux<User> result = cacheService.getCache(ID, CACHE_NAME_USER, User.class, () -> {
            retrievals.incrementAndGet();
            return Flux.just(first, second).delayElements(Duration.ofMillis(75));
        });

        assertTrue(timings().isEmpty());
        StepVerifier.create(result).expectNext(first, second).verifyComplete();

        assertEquals(1, awaitTimings(1).size());
        Matcher matcher = timing(awaitTimings(1).get(0));
        assertTrue(Long.parseLong(matcher.group(1)) >= 140);
        assertEquals("success", matcher.group(2));
        assertEquals(1, retrievals.get());
    }

    @Test
    void separateSubscriptionsAreTimedIndependently() throws InterruptedException {
        Mono<User> result = cacheService.getCache(ID, CACHE_NAME_USER,
                () -> Mono.delay(Duration.ofMillis(20)).thenReturn(user(ID)), User.class);

        StepVerifier.create(result).expectNextCount(1).verifyComplete();
        assertEquals(1, awaitTimings(1).size());
        StepVerifier.create(result).expectNextCount(1).verifyComplete();
        assertEquals(2, awaitTimings(2).size());
    }

    @Test
    void emptyReadsLogSuccess() throws InterruptedException {
        StepVerifier.create(cacheService.getCache(ID, CACHE_NAME_USER, Mono::<User>empty, User.class))
                .verifyComplete();
        StepVerifier.create(cacheService.getCache(ID, CACHE_NAME_USER, User.class, Flux::<User>empty))
                .verifyComplete();

        assertEquals(2, awaitTimings(2).size());
        awaitTimings(2).forEach(event -> assertEquals("success", timing(event).group(2)));
    }

    @Test
    void failedReadsLogErrorAndPropagateWithoutLeakingDetails() throws InterruptedException {
        IllegalStateException failure = new IllegalStateException("secret-failure-detail");

        StepVerifier.create(cacheService.getCache(ID, CACHE_NAME_USER, () -> Mono.<User>error(failure), User.class))
                .expectErrorMatches(error -> error == failure).verify();
        StepVerifier.create(cacheService.getCache(ID, CACHE_NAME_USER, User.class, () -> Flux.<User>error(failure)))
                .expectErrorMatches(error -> error == failure).verify();

        assertEquals(2, awaitTimings(2).size());
        awaitTimings(2).forEach(event -> {
            assertEquals("error", timing(event).group(2));
            assertTrue(!event.getMessage().getFormattedMessage().contains("secret-failure-detail"));
            assertTrue(!event.getMessage().getFormattedMessage().contains(REDIS_KEY));
        });
    }

    @Test
    void cancelledReadsLogCancelled() throws InterruptedException {
        StepVerifier.create(cacheService.getCache(ID, CACHE_NAME_USER, Mono::<User>never, User.class))
                .thenAwait(Duration.ofMillis(10)).thenCancel().verify(Duration.ofSeconds(2));
        StepVerifier.create(cacheService.getCache(ID, CACHE_NAME_USER, User.class, Flux::<User>never))
                .thenAwait(Duration.ofMillis(10)).thenCancel().verify(Duration.ofSeconds(2));

        assertEquals(2, awaitTimings(2).size());
        awaitTimings(2).forEach(event -> assertEquals("cancelled", timing(event).group(2)));
    }

    @Test
    void instrumentationDoesNotChangeCacheOperationsOrMetrics() {
        SimpleMeterRegistry directRegistry = new SimpleMeterRegistry();
        CacheServiceImpl direct = newService(directRegistry);
        AtomicInteger retrievals = new AtomicInteger();
        User user = user(ID);

        StepVerifier.create(direct.getCache(ID, CACHE_NAME_USER, () -> {
            retrievals.incrementAndGet();
            return Mono.just(user);
        }, User.class)).expectNext(user).verifyComplete();
        StepVerifier.create(cacheService.getCache(ID, CACHE_NAME_USER, () -> {
            retrievals.incrementAndGet();
            return Mono.just(user);
        }, User.class)).expectNext(user).verifyComplete();

        assertEquals(2, retrievals.get());
        verify(hashOperations, times(2)).get(REDIS_KEY, ID);
        verify(hashOperations, times(2)).put(anyString(), anyLong(), anyString());
        assertEquals(meterSummary(directRegistry), meterSummary(meterRegistry));
    }

    private List<String> meterSummary(SimpleMeterRegistry registry) {
        return registry.getMeters().stream()
                .map(meter -> meter.getId().getName() + meter.getId().getTags() + "="
                        + count(meter))
                .sorted().toList();
    }

    private long count(Meter meter) {
        return meter instanceof io.micrometer.core.instrument.Timer timer ? timer.count()
                : (long) meter.measure().iterator().next().getValue();
    }
}
