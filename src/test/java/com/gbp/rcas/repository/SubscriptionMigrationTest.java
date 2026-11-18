package com.gbp.rcas.repository;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.PostgreSQLContainer;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

class SubscriptionMigrationTest {
    private static final PostgreSQLContainer<?> DATABASE = new PostgreSQLContainer<>("postgres:15.2")
            .withDatabaseName("testdb").withUsername("test").withPassword("test");

    @BeforeAll
    static void start() {
        DATABASE.start();
    }

    @AfterAll
    static void stop() {
        DATABASE.stop();
    }

    @BeforeEach
    void reset() throws SQLException {
        execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public");
    }

    @Test
    void freshSchemaSeedsAndEnforcesGuardForInsertUpdateDeleteAndTruncate() throws Exception {
        executeFile("db.migration/init.sql");
        executeFile("db.migration/V2__InsertUser.sql");
        executeFile("db.migration/V3__InsertSubscription.sql");
        assertThat(number("SELECT count(*) FROM pg_inherits WHERE inhparent = 'subscription'::regclass"))
                .isEqualTo(4);
        assertThat(number("SELECT count(*) FROM subscription_type_registry")).isEqualTo(3);
        assertThrows(SQLException.class,
                () -> execute("INSERT INTO subscription(type, active, user_id) VALUES ('1', 1, 1)"));
        assertThrows(SQLException.class, () -> execute("DELETE FROM subscription_type_registry WHERE type = '1'"));
        execute("UPDATE subscription SET id = 100, type = 'renamed' WHERE id = 1");
        assertThat(number("SELECT count(*) FROM subscription_type_registry "
                + "WHERE subscription_id = 100 AND type = 'renamed'")).isEqualTo(1);
        execute("DELETE FROM subscription WHERE id = 100");
        assertThat(number("SELECT count(*) FROM subscription_type_registry WHERE subscription_id = 100"))
                .isZero();
        execute("TRUNCATE subscription RESTART IDENTITY CASCADE");
        assertThat(number("SELECT count(*) FROM subscription_type_registry")).isZero();
    }

    @Test
    void migrationPreservesRowsAndHighWaterSequence() throws Exception {
        legacySchema();
        execute("INSERT INTO subscription VALUES (10, 'first', 1, 9), (250, 'second', 0, 1)");
        execute("SELECT setval('subscription_id_seq', 300)");
        executeFile("db.migration/V4__PartitionSubscription.sql");
        assertThat(number("SELECT count(*) FROM subscription")).isEqualTo(2);
        assertThat(number("SELECT count(*) FROM subscription s JOIN subscription_legacy l USING (id, type, active, user_id)"))
                .isEqualTo(2);
        assertThat(number("SELECT count(*) FROM subscription_type_registry")).isEqualTo(2);
        assertThat(number("INSERT INTO subscription(type, active, user_id) VALUES ('next', 1, 9) RETURNING id"))
                .isEqualTo(301);
        assertThat(number("SELECT count(*) FROM subscription WHERE user_id = 9")).isEqualTo(2);
    }

    @Test
    void migrationHandlesAnEmptyLegacyTable() throws Exception {
        legacySchema();
        executeFile("db.migration/V4__PartitionSubscription.sql");
        assertThat(number("SELECT count(*) FROM pg_inherits WHERE inhparent = 'subscription'::regclass"))
                .isEqualTo(4);
        assertThat(number("INSERT INTO subscription(type, active, user_id) VALUES ('first', 1, 1) RETURNING id"))
                .isEqualTo(1);
    }

    @Test
    void rollbackAfterNewWritesCopiesAuthoritativeDataBack() throws Exception {
        legacySchema();
        execute("INSERT INTO subscription VALUES (10, 'first', 1, 9)");
        executeFile("db.migration/V4__PartitionSubscription.sql");
        execute("UPDATE subscription SET type = 'changed' WHERE id = 10");
        execute("INSERT INTO subscription VALUES (900, 'new', 0, 1)");
        execute("BEGIN; LOCK TABLE subscription, subscription_legacy IN ACCESS EXCLUSIVE MODE; "
                + "TRUNCATE subscription_legacy; "
                + "INSERT INTO subscription_legacy (id, type, active, user_id) SELECT id, type, active, user_id FROM subscription; "
                + "ALTER SEQUENCE subscription_id_seq OWNED BY subscription_legacy.id; "
                + "ALTER TABLE subscription_legacy ALTER COLUMN id SET DEFAULT nextval('subscription_id_seq'); "
                + "SELECT setval('subscription_id_seq', GREATEST((SELECT last_value FROM subscription_id_seq), max(id)), true) "
                + "FROM subscription_legacy HAVING max(id) IS NOT NULL AND max(id) >= (SELECT last_value FROM subscription_id_seq); "
                + "DROP TABLE subscription CASCADE; DROP TABLE subscription_type_registry; "
                + "DROP FUNCTION sync_subscription_type_registry(); ALTER TABLE subscription_legacy RENAME TO subscription; COMMIT");
        assertThat(number("SELECT count(*) FROM subscription WHERE (id = 10 AND type = 'changed') "
                + "OR (id = 900 AND type = 'new')")).isEqualTo(2);
        assertThat(number("INSERT INTO subscription(type, active, user_id) VALUES ('next', 1, 1) RETURNING id"))
                .isGreaterThan(900);
    }

    @Test
    void migrationRejectsInvalidOrDependentLegacyTablesWithoutSwapping() throws Exception {
        legacySchema();
        execute("ALTER TABLE subscription DROP CONSTRAINT subscription_type_key");
        execute("INSERT INTO subscription VALUES (1, 'same', 1, 1), (2, 'same', 1, 1)");
        assertThrows(SQLException.class, () -> executeFile("db.migration/V4__PartitionSubscription.sql"));
        assertThat(number("SELECT count(*) FROM subscription")).isEqualTo(2);
        execute("DELETE FROM subscription WHERE id = 2; CREATE VIEW subscription_view AS SELECT * FROM subscription");
        assertThrows(SQLException.class, () -> executeFile("db.migration/V4__PartitionSubscription.sql"));
        assertThat(number("SELECT count(*) FROM subscription_view")).isEqualTo(1);
    }

    @Test
    void concurrentDuplicateTypesCannotBothCommit() throws Exception {
        executeFile("db.migration/init.sql");
        var executor = Executors.newFixedThreadPool(2);
        var start = new CountDownLatch(1);
        try {
            var first = executor.submit(() -> insertSameType(start));
            var second = executor.submit(() -> insertSameType(start));
            start.countDown();
            assertThat((first.get(20, TimeUnit.SECONDS) ? 1 : 0) + (second.get(20, TimeUnit.SECONDS) ? 1 : 0))
                    .isEqualTo(1);
            assertThat(number("SELECT count(*) FROM subscription WHERE type = 'contended'")).isEqualTo(1);
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void startupPopulatorIsIdempotentAfterMigrationAndDoesNotLowerSequences() throws Exception {
        legacySchema();
        execute("CREATE TABLE user_t (id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL, "
                + "password VARCHAR(50) NOT NULL, email VARCHAR(255) UNIQUE NOT NULL, created_on TIMESTAMP NOT NULL)");
        execute("INSERT INTO subscription VALUES (5, 'original', 1, 1)");
        executeFile("db.migration/V4__PartitionSubscription.sql");
        execute("SELECT setval('subscription_id_seq', 5000); SELECT setval('user_t_id_seq', 6000)");
        runPopulator();
        runPopulator();
        assertThat(number("SELECT count(*) FROM user_t WHERE id BETWEEN 1000 AND 1002")).isEqualTo(3);
        assertThat(number("SELECT count(*) FROM subscription WHERE id BETWEEN 1001 AND 1004")).isEqualTo(4);
        assertThat(number("SELECT count(*) FROM subscription_type_registry")).isEqualTo(5);
        assertThat(number("INSERT INTO subscription(type, active, user_id) VALUES ('after-seed', 1, 1000) RETURNING id"))
                .isGreaterThan(5000);
        assertThat(number("INSERT INTO user_t(username, password, email, created_on) "
                + "VALUES ('after-seed', 'password', 'after-seed@example.com', now()) RETURNING id"))
                .isGreaterThan(6000);
    }

    @Test
    void startupPopulatorLeavesExistingConflictingIdsAndTypesUntouched() throws Exception {
        executeFile("db.migration/init.sql");
        execute("INSERT INTO subscription VALUES (1001, 'occupied-id', 1, 42), (10, 'populator-1002', 1, 42)");
        runPopulator();
        assertThat(number("SELECT count(*) FROM subscription WHERE user_id = 42")).isEqualTo(2);
        assertThat(number("SELECT count(*) FROM subscription WHERE type IN ('populator-1001', 'populator-1002')"))
                .isEqualTo(1);
        assertThat(number("SELECT count(*) FROM subscription_type_registry")).isEqualTo(4);
    }

    private void runPopulator() throws Exception {
        var processBuilder = new ProcessBuilder("bash", "scripts/startup-service-records-populator.sh");
        processBuilder.environment().put("COMPOSE", "bash src/test/resources/docker-compose-testcontainer.sh");
        processBuilder.environment().put("TEST_POSTGRES_CONTAINER", DATABASE.getContainerId());
        processBuilder.redirectErrorStream(true);
        Process process = processBuilder.start();
        assertThat(process.waitFor(30, TimeUnit.SECONDS)).isTrue();
        String output = new String(process.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        assertThat(process.exitValue()).as(output).isZero();
    }

    private boolean insertSameType(CountDownLatch start) throws InterruptedException {
        start.await();
        try {
            execute("INSERT INTO subscription(type, active, user_id) VALUES ('contended', 1, 1)");
            return true;
        } catch (SQLException ex) {
            assertThat(ex.getSQLState()).isEqualTo("23505");
            return false;
        }
    }

    private void legacySchema() throws SQLException {
        execute("CREATE TABLE subscription (id SERIAL PRIMARY KEY, type VARCHAR(50) UNIQUE NOT NULL, "
                + "active INT NOT NULL, user_id INT NOT NULL)");
    }

    private void executeFile(String file) throws Exception {
        execute(Files.readString(Path.of(file)));
    }

    private Connection connection() throws SQLException {
        return DriverManager.getConnection(DATABASE.getJdbcUrl(), DATABASE.getUsername(), DATABASE.getPassword());
    }

    private void execute(String sql) throws SQLException {
        try (Connection connection = connection(); Statement statement = connection.createStatement()) {
            statement.execute(sql);
        }
    }

    private long number(String sql) throws SQLException {
        try (Connection connection = connection(); Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery(sql)) {
            result.next();
            return result.getLong(1);
        }
    }
}
