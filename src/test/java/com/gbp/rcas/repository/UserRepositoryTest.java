package com.gbp.rcas.repository;

import com.gbp.rcas.model.User;
import com.gbp.rcas.model.Subscription;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.util.TestPropertyValues;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ApplicationListener;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.event.ContextClosedEvent;
import org.springframework.data.r2dbc.core.R2dbcEntityTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.ContextConfiguration;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;
import org.testcontainers.utility.MountableFile;

import java.sql.Timestamp;
import java.util.Date;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.data.relational.core.query.Criteria.where;
import static org.springframework.data.relational.core.query.Query.query;

@SpringBootTest
@ActiveProfiles("test-tc")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
@ContextConfiguration(initializers = UserRepositoryTest.TestContainerInitializer.class)
public class UserRepositoryTest {

    private static final Logger logger = LoggerFactory.getLogger(UserRepositoryTest.class);

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
    private R2dbcEntityTemplate template;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private SubscriptionRepository subscriptionRepository;

    @Test
    void subscriptionRepositoryReadsAndWritesPartitionedRows() {
        Subscription row = new Subscription(null, "repository-partition-test", 1, 12345);
        template.insert(row)
                .flatMap(saved -> subscriptionRepository.findById(saved.getId()))
                .as(StepVerifier::create)
                .assertNext(saved -> {
                    assertThat(saved.getType()).isEqualTo("repository-partition-test");
                    assertThat(saved.getUser_id()).isEqualTo(12345);
                })
                .verifyComplete();

        subscriptionRepository.findSubscriptionsByUserId(12345L)
                .as(StepVerifier::create)
                .assertNext(saved -> assertThat(saved.getType()).isEqualTo("repository-partition-test"))
                .verifyComplete();
    }

//    @BeforeEach
//    public void setup() throws IOException, InterruptedException {
//        this.template.delete(User.class).all().block(Duration.ofSeconds(5));
//         // Restore database from dump in /tmp folder
//         // postgreSQLContainer
//         //   .execInContainer("pg_restore","-U", "test", "-w", "--data-only", "--disable-triggers", "--dbname=test", "/tmp/backup");
//    }

    @Test
    @DisplayName("UserRepository.testDatabaseClientExisted - Success")
    @Order(1)
    public void testDatabaseClientExisted() {
        assertNotNull(template);
    }

    @Test
    @DisplayName("UserRepository.testUserRepositoryExisted - Success")
    @Order(2)
    public void testUserRepositoryExisted() {
        assertNotNull(userRepository);
    }

    @Test
    @DisplayName("UserRepository.testRedisContainerIsRunning - Success")
    @Order(3)
    void givenPostgresContainerConfiguredWithDynamicProperties_whenCheckingRunningStatus_thenStatusIsRunning() {
        assertTrue(postgreSQLContainer.isRunning());
    }

    @Test
    @DisplayName("UserRepository.testRedisContainerIsRunning - Success")
    @Order(4)
    void givenRedisContainerConfiguredWithDynamicProperties_whenCheckingRunningStatus_thenStatusIsRunning() {
        assertTrue(redisContainer.isRunning());
    }

    @Test
    @DisplayName("UserRepository.findById - Success")
    @Order(5)
    public void givenUserId_whenGetUserById_thenUserFound() {

        Mono<User> user = template.select(User.class)
                .matching(query(where("id").is(1)))
                .one();

        user.as(StepVerifier::create)
                .assertNext(u -> {
                    logger.info("{} was not found: id - {}, username - {}, password - {}, email - {}", User.class, u.getId(), u.getUsername(), u.getPassword(), u.getEmail());
                    assertThat(u.getId()).isEqualTo(1);
                })
                .verifyComplete();

    }

    @Test
    @DisplayName("UserRepository.findById - Not Found")
    @Order(6)
    public void givenUserId_whenGetUserById_thenUserNotFound() {

        Mono<User> user = template.select(User.class)
                .matching(query(where("id").is(9_999_999_999L)))
                .one();

        StepVerifier
                .create(user)
                .expectNextCount(0)
                .verifyComplete();

    }

    @Test
    @DisplayName("UserRepository.testSelectAll - Success")
    @Order(7)
    public void testSelectAll() {

        Flux<User> user = template.select(User.class)
                .matching(query(where("id").lessThanOrEquals(3)))
                .all();

        StepVerifier
                .create(user)
                .expectNextCount(3)
                .verifyComplete();

    }

    @Test
    @DisplayName("UserRepository.testInsertAndQuery - Success")
    @Order(8)
    public void testInsertAndQuery() {

        Long userId = Long.valueOf(4L);
        var user = new User.UserBuilder()
                .setId(userId)
                        .setUsername("martinslavov")
                                .setPassword("password")
                                        .setEmail("slavoff@gmail.com")
                                                .setCreatedOn(new Timestamp(new Date().getTime()))
                .createUser();

        this.template.insert(user)
                .thenMany(
                        this.userRepository.findUserById(userId)
                )
                .log()
                .as(StepVerifier::create)
                .consumeNextWith(u -> {
                            logger.info("{} was saved: id - {}, username - {}, password - {}, email - {}", User.class, u.getId(), u.getUsername(), u.getPassword(), u.getEmail());
                            assertThat(u.getId()).isEqualTo(userId);
                        }
                )
                .verifyComplete();

    }

    @AfterAll
    public static void tearDown(){
        postgreSQLContainer.stop();
        redisContainer.stop();
    }

}
