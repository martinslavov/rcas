package com.gbp.rcas.aop;

import org.junit.jupiter.api.Test;
import org.springframework.aop.aspectj.annotation.AspectJProxyFactory;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ExecutionTimeAspectTest {

    static class Target {
        @MeasureExecutionTime
        public String sync() {
            return "ok";
        }

        @MeasureExecutionTime
        public String syncFail() {
            throw new IllegalStateException("boom");
        }

        @MeasureExecutionTime
        public Mono<String> mono() {
            return Mono.just("m");
        }

        @MeasureExecutionTime
        public Mono<String> monoFail() {
            return Mono.error(new IllegalArgumentException("bad"));
        }

        @MeasureExecutionTime
        public Mono<String> monoThrows() {
            throw new IllegalStateException("sync");
        }

        @MeasureExecutionTime
        public Flux<Integer> flux() {
            return Flux.just(1, 2);
        }

        @MeasureExecutionTime
        public Flux<Integer> fluxThrows() {
            throw new IllegalStateException("sync");
        }
    }

    private Target proxy(Target target) {
        AspectJProxyFactory factory = new AspectJProxyFactory(target);
        factory.setProxyTargetClass(true);
        factory.addAspect(new ExecutionTimeAspect());
        return factory.getProxy();
    }

    @Test
    void syncResultIsReturnedAndExceptionsPropagate() {
        Target target = proxy(new Target());

        assertEquals("ok", target.sync());
        assertThrows(IllegalStateException.class, target::syncFail);
    }

    @Test
    void monoResultIsReturnedUnchanged() {
        Target target = proxy(new Target());

        StepVerifier.create(target.mono()).expectNext("m").verifyComplete();
    }

    @Test
    void reactiveErrorsAndAssemblyExceptionsPropagate() {
        Target target = proxy(new Target());

        StepVerifier.create(target.monoFail()).expectError(IllegalArgumentException.class).verify();
        assertThrows(IllegalStateException.class, target::monoThrows);
    }

    @Test
    void fluxEmitsAllItemsAndPropagatesErrors() {
        Target target = proxy(new Target());

        StepVerifier.create(target.flux()).expectNext(1, 2).verifyComplete();
        assertThrows(IllegalStateException.class, target::fluxThrows);
    }

    @Test
    void cancellationIsNotAltered() {
        Target target = proxy(new Target());

        StepVerifier.create(target.flux()).expectNext(1).thenCancel().verify(Duration.ofSeconds(1));
    }
}
