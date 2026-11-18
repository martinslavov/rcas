package com.gbp.rcas.handler;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webtestclient.autoconfigure.AutoConfigureWebTestClient;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.util.TestPropertyValues;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ApplicationListener;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.event.ContextClosedEvent;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;
import org.testcontainers.utility.MountableFile;

@SpringBootTest
@AutoConfigureWebTestClient
@ActiveProfiles("test-tc")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
@ContextConfiguration(initializers = UserHandlerIntegrationTest.TestContainerInitializer.class)
public class UserHandlerIntegrationTest {

    private static final Logger logger = LoggerFactory.getLogger(UserHandlerIntegrationTest.class);

    private static PostgreSQLContainer postgreSQLContainer;

    private static GenericContainer<?> redisContainer;

    static class TestContainerInitializer implements ApplicationContextInitializer<ConfigurableApplicationContext> {

        @Override
        public void initialize(ConfigurableApplicationContext configurableApplicationContext) {
            postgreSQLContainer = new PostgreSQLContainer<>("postgres:15.2")
                    .withCopyFileToContainer(MountableFile.forClasspathResource("db/migration/"), "/docker-entrypoint-initdb.d/");
            postgreSQLContainer.start();
            logger.info("container.getFirstMappedPort():: {}", postgreSQLContainer.getFirstMappedPort());
            configurableApplicationContext
                    .addApplicationListener((ApplicationListener<ContextClosedEvent>) event -> postgreSQLContainer.stop());
            TestPropertyValues
                    .of(
                            "spring.r2dbc.url=" +  "r2dbc:postgresql://"
                                    + postgreSQLContainer.getHost() + ":" + postgreSQLContainer.getFirstMappedPort()
                                    + "/" + postgreSQLContainer.getDatabaseName(),
                            "spring.r2dbc.username=" + postgreSQLContainer.getUsername(),
                            "spring.r2dbc.password=" + postgreSQLContainer.getPassword()
                    )
                    .applyTo(configurableApplicationContext);

            redisContainer = new GenericContainer<>(DockerImageName.parse("redis:7.0.9-alpine")).withExposedPorts(6379);
            redisContainer.start();
            System.setProperty("spring.data.redis.host", redisContainer.getHost());
            System.setProperty("spring.data.redis.port", redisContainer.getFirstMappedPort().toString());
        }
    }

    @Autowired
    private WebTestClient webTestClient;

    @Test
    @DisplayName("UserHandler.findById - Success")
    @Order(1)
    public void givenUserId_whenGetUserById_thenUserFound() {
        // Given
        Long userId = Long.valueOf(1);

        // Then
        webTestClient.get()
                .uri("/user/{id}", userId)
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.user.id")
                .isEqualTo(userId);
    }

    @Test
    @DisplayName("UserHandler.findById - Not Found")
    @Order(2)
    public void givenUserId_whenGetUserById_thenUserNotFound() {
        // Given
        Long userId = Long.valueOf(9_999_999_999L);

        // Then
        webTestClient.get()
                .uri("/user/{id}", userId)
                .exchange()
                .expectStatus()
                .isNotFound()
                .expectBody()
                .jsonPath("$.user")
                .doesNotExist();
    }

    @AfterAll
    public static void tearDown(){
        postgreSQLContainer.stop();
        redisContainer.stop();
    }
}
