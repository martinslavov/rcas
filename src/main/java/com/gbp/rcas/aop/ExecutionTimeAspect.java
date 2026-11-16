package com.gbp.rcas.aop;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.SignalType;

import java.util.concurrent.TimeUnit;

@Aspect
@Component
public class ExecutionTimeAspect {

    private static final Logger logger = LoggerFactory.getLogger(ExecutionTimeAspect.class);

    private static final String OUTCOME_SUCCESS = "success";
    private static final String OUTCOME_ERROR = "error";
    private static final String OUTCOME_CANCELLED = "cancelled";

    @Around("@annotation(com.gbp.rcas.aop.MeasureExecutionTime)")
    public Object measure(ProceedingJoinPoint joinPoint) throws Throwable {
        MethodSignature signature = (MethodSignature) joinPoint.getSignature();
        String method = signature.getDeclaringType().getSimpleName() + "." + signature.getName();
        Class<?> returnType = signature.getReturnType();

        if (Mono.class.isAssignableFrom(returnType)) {
            Mono<?> mono = (Mono<?>) joinPoint.proceed();
            return Mono.defer(() -> {
                long start = System.nanoTime();
                return mono.doFinally(signal -> log(method, start, outcome(signal)));
            });
        }
        if (Flux.class.isAssignableFrom(returnType)) {
            Flux<?> flux = (Flux<?>) joinPoint.proceed();
            return Flux.defer(() -> {
                long start = System.nanoTime();
                return flux.doFinally(signal -> log(method, start, outcome(signal)));
            });
        }

        long start = System.nanoTime();
        String outcome = OUTCOME_ERROR;
        try {
            Object result = joinPoint.proceed();
            outcome = OUTCOME_SUCCESS;
            return result;
        } finally {
            log(method, start, outcome);
        }
    }

    private String outcome(SignalType signal) {
        return switch (signal) {
            case ON_ERROR -> OUTCOME_ERROR;
            case CANCEL -> OUTCOME_CANCELLED;
            default -> OUTCOME_SUCCESS;
        };
    }

    private void log(String method, long startNanos, String outcome) {
        long millis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startNanos);
        logger.info("{} executed in {} ms ({})", method, millis, outcome);
    }
}
