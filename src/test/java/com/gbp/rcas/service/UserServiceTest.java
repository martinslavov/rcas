package com.gbp.rcas.service;

import com.gbp.rcas.model.User;
import com.gbp.rcas.repository.UserRepository;

import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import java.sql.Timestamp;
import java.util.Date;

import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import static com.gbp.rcas.config.Constants.CACHE_NAME_USER;
import static org.junit.jupiter.api.Assertions.assertAll;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.verify;

@SpringBootTest
@ActiveProfiles("test-tc")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
public class UserServiceTest {

    @Autowired
    private UserService userService;

    @MockitoBean
    private CacheService cacheService;

    @MockitoBean
    private UserRepository userRepository;

    @Test
    @DisplayName("UserService.findById - Success")
    @Order(1)
    void test_findById_Success() {
        // Given - Set up the cache service response
        Long userId = Long.valueOf(1);
        var user = new User.UserBuilder()
                .setId(userId)
                        .setUsername("mslavov")
                                .setPassword("mypassword")
                                        .setEmail("slavoff.martin@gmail.com")
                                                .setCreatedOn(new Timestamp(new Date().getTime()))
                .createUser();
        doReturn(Mono.just(user)).when(cacheService)
                .getCache(eq(userId), eq(CACHE_NAME_USER), any(), eq(User.class));

        // When -  Execute the service call
        Mono<User> returnedUser = userService.findById(userId);

        // Then - Assert the response
        StepVerifier.create(returnedUser)
                .assertNext(u -> assertAll(
                            () -> Assertions.assertNotNull(u.getId()),
                            () -> Assertions.assertEquals(u.getId(), userId)
                        )
                )
                .expectComplete()
                .verify();
        verify(cacheService).getCache(eq(userId), eq(CACHE_NAME_USER), any(), eq(User.class));
    }

    @Test
    @DisplayName("UserService.findById - Not found")
    @Order(2)
    void test_findById_NotFound() {
        // Given - Set up an empty cache result
        Long userId = Long.valueOf(9_999_999_999L);
        doReturn(Mono.empty()).when(cacheService)
                .getCache(eq(userId), eq(CACHE_NAME_USER), any(), eq(User.class));

        // When -  Execute the service call
        Mono<User> returnedUser = userService.findById(userId);

        // Then - Assert the response
        StepVerifier.create(returnedUser)
                .expectNextCount(0)
                .expectComplete()
                .verify();
    }

    @Test
    @Order(3)
    @DisplayName("UserService.findById - IllegalArgumentException")
    public void test_findById_IllegalArgumentException() {
        // Given - Set up the cache service error
        Long userId = Long.valueOf(-1);
        doReturn(Mono.error(new IllegalArgumentException())).when(cacheService)
                .getCache(eq(userId), eq(CACHE_NAME_USER), any(), eq(User.class));

        // When -  Execute the service call
        Mono<User> returnedUser = userService.findById(userId);

        // Then - Assert the response
        StepVerifier.create(returnedUser)
                .verifyError(IllegalArgumentException.class);
    }
}
