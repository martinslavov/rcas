package com.gbp.rcas.aop;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Logs the execution time of a public method of a Spring-managed bean (called through its proxy).
 * For {@code Mono}/{@code Flux} results the time is measured from subscription to termination.
 */
@Documented
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeasureExecutionTime {
}
