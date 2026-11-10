# Code review guidelines

Source of the static review rules: `.github/checkstyle/checkstyle.xml` implements the automatable parts and is run by the
`CI Static Review` workflow (`./gradlew checkstyleMain checkstyleTest`) on every pull request. The rest is for human reviewers.

## Project context

RCAS is a reactive cache service: Spring Boot WebFlux, a two-level cache (Caffeine L1, Redis L2) and PostgreSQL through
R2DBC. Java 25, Gradle, JUnit 5 for unit and integration tests (Testcontainers), and a separate `component-tests`
Gradle project that runs HTTP tests against the docker compose stack. All layers must stay non-blocking.

## General review focus

- Keep everything **simple and clear**: readability and maintainability come first.
- **Ignore business logic and domain rules**; focus on structure, design and code quality.
- Follow the **SOLID** principles where possible:
  - **S:** Single Responsibility, one purpose per class or function.
  - **O:** Open/Closed, easy to extend and not to modify.
  - **L:** Liskov Substitution, subclasses behave consistently with their base class.
  - **I:** Interface Segregation, avoid bloated interfaces.
  - **D:** Dependency Inversion, depend on abstractions and not on concretions.
- Always keep the **DRY** principle in mind.
- Keep functions and classes **short, focused and testable**.
- Prefer **composition over inheritance**.
- Avoid unnecessary abstractions and "clever" designs: simple is better.

## Code quality standards

- Ensure a **readable, maintainable** structure and consistent formatting.
- Check function and class size, complexity and **responsibility**.
- Confirm **consistent naming** (camelCase for methods and variables, PascalCase for classes, UPPER_SNAKE_CASE for
  constants) and a logical package organization (`com.gbp.rcas`).
- Validate proper **error handling** and avoid leaking internal information in responses and logs.
- Eliminate **dead code**, **redundant logic** and **overengineering**.
- Enforce **clean architecture principles** and separation of concerns.
- Reactive code: flag **blocking calls** (`block()`, `Thread.sleep`, blocking I/O) and missing error handling in
  `Mono` / `Flux` pipelines.

## Structural and design review

- Review the **dependency structure**: modules should be loosely coupled.
- Identify **violations of SOLID or DRY**.
- Look for **code smells** such as long methods, large classes and hidden dependencies.
- Confirm **testability**: code should be easy to mock and unit test, and new behavior should come with tests.
- Check that coverage does not drop below the JaCoCo minimums in `build.gradle` (LINE 45 %, BRANCH 15 %; enforced by `./gradlew build`, report with `./gradlew jacocoTestReport`).
- Check that secrets and credentials are not committed and that workflow changes keep least-privilege `permissions`.

## Review communication

- Provide **concise, actionable feedback** with examples where possible.
- Keep feedback **positive, respectful and educational**.
- Avoid theory-heavy explanations: focus on _why_ the change improves simplicity or structure.
- Acknowledge **good practices** and clean patterns.
- Ask clarifying questions only when the context is unclear.
- Focus on **improvement, not criticism**.

## Review comment format

Use this structure for every comment:

- **Issue:** describe what needs attention
- **Suggestion:** provide a clear, simple improvement or example
- **Why:** explain briefly how this improves simplicity, structure or adherence to our quality and design standards
