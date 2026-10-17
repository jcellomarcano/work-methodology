# Gradle conventions: official baseline + typical house rules

## 1. Source and hierarchy

The baseline is Gradle's "Best Practices for Authoring Gradle Builds" (seven pages), plus the user guide
pages on the Wrapper, dependency verification, version catalogs, both caches, Kotlin DSL and toolchains.
They were read on 2026-10-15 under `https://docs.gradle.org/current/userguide/` (`UG/`), with every page
header showing **version 9.8.1** (Measured), so the quotes are pinned to 9.8.1. The guide calls itself
non-universal ("Not every practice here will be applicable to every build"). Project deltas go in
`CONVENTIONS.md`. Build files are owner-gated (`00-principles` §4, §5): this page is for review only.

## 2. What the official guide says, verbatim

| Practice | Exact quote | URL#anchor |
|---|---|---|
| Always the Wrapper | "It is always recommended to execute a build with the Wrapper to ensure a reliable, controlled, and standardized execution of the build." | `UG/gradle_wrapper.html#sec:using_wrapper` |
| Wrapper in VCS | "To make the Wrapper files available to other developers and execution environments, you need to check them into version control." | `UG/gradle_wrapper.html#sec:adding_wrapper` |
| Wrapper not hand-edited | "Do not edit the wrapper files manually." | `UG/gradle_wrapper_basics.html#sec:view_the_wrapper` |
| Wrapper is sensitive | "You should treat any change to the Wrapper as security-sensitive." | `UG/best_practices_security.html#validate_wrapper_checksum` |
| Distribution checksum | "Always set the distributionSha256Sum property in your gradle-wrapper.properties file to verify the integrity of the downloaded Gradle distribution." | `UG/best_practices_security.html#validate_gradle_checksum` |
| Scripts are code | "Build scripts (build.gradle, settings.gradle, etc.) can also execute arbitrary code during the configuration phase." | `UG/best_practices_security.html#run_gradle_on_external_projects` |
| Reproducible output | "A build is reproducible when the same source code produces byte-for-byte identical output files, on any machine, at any time." | `UG/best_practices_security.html#builds_should_be_reproducible` |
| Publishing builds | "Do not use incremental, local, or cached builds when publishing." | `UG/best_practices_security.html#build-published-artifacts-securely` |
| Verification bootstrap | "This is why you must review the generated verification file." | `UG/dependency_verification.html#sec:bootstrapping-verification` |
| `strict` (the default) | "Verification fails as early as possible to avoid using compromised dependencies during the build" | `UG/dependency_verification.html#sec:disabling-verification` |
| Verification's scope | "Dependency verification is meant to protect yourself from compromised dependencies, not to prevent you from including vulnerable dependencies." | `UG/dependency_verification.html` (preamble, no anchor) |
| Version catalog | "When you define your dependency versions in a single, shared version catalog, you reduce duplication and make upgrades easier." | `UG/best_practices_dependencies.html#use_version_catalogs` |
| Catalog ≠ enforcement | "Version catalogs declare requested versions but do not enforce them." | `UG/version_catalogs.html` (preamble, no anchor) |
| Dynamic versions | "To ensure reproducible builds, it’s necessary to lock versions of dependencies and their transitive dependencies." | `UG/dependency_locking.html` (preamble, no anchor) |
| Repositories | "Declare your repositories for your plugins and dependencies in settings.gradle.kts." | `UG/best_practices_dependencies.html#set_up_repositories_in_settings` |
| Kotlin DSL | "Prefer the Kotlin DSL (build.gradle.kts) over the Groovy DSL (build.gradle) when authoring new builds or creating new subprojects in existing builds." | `UG/best_practices_general.html#use_kotlin_dsl` |
| `plugins {}` | "You should always use the plugins block to apply plugins in your build scripts." | `UG/best_practices_general.html#use_the_plugins_block` |
| Latest minor | "Stay on the latest minor version of the major Gradle release you’re using, and regularly update your plugins to the latest compatible versions." | `UG/best_practices_general.html#use_latest_minor_versions` |
| Root `gradle.properties` | "This file should be added to source control in order to share these properties across different machines and between developers." | `UG/best_practices_general.html#use_the_gradle_properties_file` |
| `afterEvaluate` | "afterEvaluate should be a last resort, not a first choice." | `UG/best_practices_general.html#avoid_after_evaluate` |
| Build logic location | "The preferred location for build logic is an included build (typically named build-logic), not in buildSrc." | `UG/best_practices_structuring_builds.html#favor_composite_builds` |
| `dependsOn` | "The task dependsOn method should only be used for lifecycle tasks (tasks without task actions)." | `UG/best_practices_tasks.html#avoid_depends_on` |
| UTF-8 | "Do not rely on the default encoding of the underlying JVM or operating system, as this may differ between environments and lead to inconsistent behavior." | `UG/best_practices_performance.html#use_utf8_encoding` |
| Build cache | "Use the Build Cache to save time by reusing outputs produced by previous builds." | `UG/best_practices_performance.html#use_build_cache` |
| Configuration cache | "The Configuration Cache is the preferred way to execute Gradle builds, but it is not enabled by default." | `UG/best_practices_performance.html#use_configuration_cache` |
| CC warning mode | "Warning mode is a migration and troubleshooting aid and not intended as a persistent way of ignoring incompatibilities." | `UG/configuration_cache_enabling.html#config_cache:usage:ignore_problems` |
| Secrets | "Store credentials in GRADLE_USER_HOME/gradle.properties." / "This is the recommended approach for repository credentials and other secrets." | `UG/configuration_cache.html#config_cache:security` |
| Remote cache | "The recommended use case for the remote build cache is that your continuous integration server populates it from clean builds while developers only load from it." | `UG/build_cache.html#sec:build_cache_configure_use_cases` |
| Toolchains | "For most users: Use Java toolchains (toolchain.languageVersion)." | `UG/toolchains.html#sec:comparison_table_for_setting_project_toolchains` |
| Build logic tests | "You should test any custom tasks or plugins you create using Gradle TestKit." | `UG/best_practices_testing.html#test_custom_types_with_testkit` |

## 3. What the official guide does NOT say

- **Nothing about who may edit build files.** "Do not edit the wrapper files manually" means use the
  `:wrapper` task; it doesn't say a person must make the change. Owner-gating is a house rule.
- **Dependency verification and locking aren't best practices.** Neither is among the index's 47
  practices (Measured). Both are documented features; the guide never requires them.
- **A version catalog doesn't pin what gets resolved.** Enforcement comes from platforms or locking.
- **The best-practice pages don't ban secrets in `gradle.properties`** (that's in the configuration cache
  security section). The root file "should be added to source control", so its contents are committed.
- **Neither cache is on by default.** Both ship commented out (`# org.gradle.caching=false`,
  `# org.gradle.configuration-cache=false`); turning either on is a decision.
- **No CI failure on deprecations**: the CLI page only describes the `--warning-mode` values. **No
  Groovy-to-Kotlin migration**: Kotlin DSL is for "new builds or creating new subprojects".
- **No numeric thresholds and no reproducibility tool**, just a manual rebuild-and-compare test.

## 4. Typical house rules (labeled as such)

- **GRD-1, build files are owner-only.** An agent proposes a diff in the change card and a person applies
  it (`00-principles` §4). Gradle, AGP, KGP and plugin upgrades are SDK bumps under the owner's protocol
  (§5). **The kit enforces it (Tested, `03-tools/tests/test_gradle_guard.py`):** one glob set in
  `lib/build_files.py` (the default, the kit template, and what `detect_repo.py` emits for a Gradle repo)
  covers `*.gradle(.kts)` at any depth, every `gradle.properties`, `gradlew*`, `gradle/wrapper/**`,
  catalogs, verification metadata and keyring, lockfiles, `buildSrc/**` and `build-logic/**`. One matcher
  feeds `guard_paths.py` (subagent deny, main session `ask`; pi runs the same hook, Inferred), the role validator,
  `rdd_risk.py` (high + owner gate) and `test_sectors.py`. Older adapted configs keep their list.
- **GRD-2, the Wrapper changes only through `./gradlew :wrapper --gradle-version X`.** The same change
  sets `distributionSha256Sum` and a `-bin` URL, and CI validates the JAR. An outside wrapper PR is
  reviewed as code execution.
- **GRD-3, dependency verification is on in CI.** `gradle/verification-metadata.xml` is committed with
  `sha256` (plus `pgp` where signed), and every `Generated by Gradle` origin is reviewed before merge.
  `lenient` is allowed locally, never in CI.
- **GRD-4, the version catalog is the single source of requested versions.** No versions in `ext`,
  constants or inline coordinates. No `+` or ranges unless locked, and no `-SNAPSHOT` on a release branch.
  Enforcing resolved versions (platform, locking) is a separate card.
- **GRD-5, no secrets in committed files.** That covers the root `gradle.properties`,
  `gradle-wrapper.properties` and scripts. Credentials live in `~/.gradle/gradle.properties` or the
  environment, are read lazily (`providers.environmentVariable()`), and go through the credentials API.
- **GRD-6, reproducible (`00-principles` §12 for the build).** The JDK toolchain is pinned, archive
  defaults are left alone, and `-Dfile.encoding=UTF-8` is set. Releases come from ephemeral CI without
  caches, so a re-emitted tag gives the same bytes (§7).
- **GRD-7, both caches on with problems kept loud.** Default `problems=fail`, with incompatible tasks
  marked one by one, never a global `warn`. For the remote cache, CI writes and developers only read.
- **GRD-8, new code follows the guide.** New modules use Kotlin DSL, `plugins {}`, no `afterEvaluate`,
  convention plugins in `build-logic` and TestKit tests. Migrating old code is its own card (§5).
- **GRD-9, the two lists do different jobs.** `shared_build_files` stops agents. `full_required_globs`
  makes `test_sectors.py` escalate to the full battery, and a shared build file escalates on its own. The
  kit template, the critical-flow example and `adopt.sh` now put the same Gradle glob set in both (Tested),
  replacing `**/build.gradle`, which missed `.kts`, `settings.gradle.kts` and `build-logic/**`. With
  `sectors: []` everything is unmapped and the full battery runs anyway (`test_sectors.py:8-10`).

## 5. How it's checked

No detector below was run against a Gradle build for this page: Inferred until a project runs them.

| Rule | Cheap detector | Better detector |
|---|---|---|
| GRD-1 owner-only | `hooks/guard_paths.py` (subagent deny) + `test_sectors.py` `full_required` | CODEOWNERS on build files (not in the kit, Unknown) |
| GRD-2 Wrapper JAR | `sha256sum gradle/wrapper/gradle-wrapper.jar` against gradle.org/release-checksums | `gradle/actions/setup-gradle` v4+ (built in) or `gradle/actions/wrapper-validation` |
| GRD-2 distribution | grep `distributionSha256Sum` in `gradle-wrapper.properties` | Gradle fails on a checksum mismatch (official) |
| GRD-3 verification | the file exists; grep `Generated by Gradle` = 0 | `strict` in CI; `--write-verification-metadata sha256 help --dry-run`, then diff |
| GRD-4 versions | grep literal `group:name:version` in `*.gradle*` (heuristic) | dependency locking (`--write-locks`, lockfiles committed) |
| GRD-5 secrets | grep `password\|token\|secret` in committed `*.properties` | a secret scanner in CI (not verified here, Unknown) |
| GRD-6 reproducible | two clean builds, compare artifact `sha256` | rebuild an old tag elsewhere vs the published binary (official) |
| GRD-7 config cache | `--configuration-cache` with `problems=fail`; HTML report in `build/reports/configuration-cache/` | `enableFeaturePreview("STABLE_CONFIGURATION_CACHE")` |
| Deprecations | `--warning-mode=all` | `--warning-mode=fail` in CI (house rule) |

## Concurrency

| Rule | Official text | Reading |
|---|---|---|
| Default | "However, by default, Gradle runs only one task at a time." (`UG/performance.html#sec:enable_parallel_execution`) | `--parallel` / `org.gradle.parallel=true` runs subprojects in parallel |
| CC parallelism | "When the Configuration Cache is enabled, all tasks can run in parallel, even within the same project, subject to their declared input/output dependencies." (`UG/configuration_cache.html#config_cache:intro:parallel_task_execution`) | order comes from declared inputs and outputs, not from script order |
| No opt-out | "Parallel task execution cannot be disabled when the Configuration Cache is active." (same anchor) | a hidden sequential assumption fails once the configuration cache is on |
| Isolation | "To share mutable state across tasks, use a Build Service." (`UG/configuration_cache.html#task_isolation_through_serialization`) | each task gets its own deserialized copy, so shared lists stop being shared |
| Worker API | "The Worker API provides the ability to break up the execution of a task action into discrete units of work and then execute that work concurrently and asynchronously." (`UG/worker_api.html#worker_api`) | parallelism inside a single task |

House rule: wire inputs and outputs, never force ordering with `dependsOn`. Shared resources go through a
Build Service, and every custom task is CC-clean before it merges.

## Sources

Read on 2026-10-15. Every page returned HTTP 200 and showed Gradle **9.8.1**; `UG/` =
`https://docs.gradle.org/current/userguide/`. Pages: `best_practices.html`, `best_practices_index.html`,
`best_practices_general.html`, `best_practices_structuring_builds.html`, `best_practices_dependencies.html`,
`best_practices_tasks.html`, `best_practices_performance.html`, `best_practices_security.html`,
`best_practices_testing.html`, `gradle_wrapper.html`, `gradle_wrapper_basics.html`,
`dependency_verification.html`, `dependency_locking.html`, `version_catalogs.html`, `platforms.html`,
`configuration_cache.html`, `configuration_cache_enabling.html`, `configuration_cache_debugging.html`,
`build_cache.html`, `kotlin_dsl.html`, `toolchains.html`, `performance.html`, `worker_api.html`,
`command_line_interface.html`. Also from the official Gradle GitHub repo (outside the user guide,
unversioned): https://github.com/gradle/actions/blob/main/docs/setup-gradle.md and
https://github.com/gradle/actions/blob/main/docs/wrapper-validation.md. Failed: `UG/reproducible_archives.html`
returned 404 and isn't cited. Not consulted: Android developers build docs and the Gradle blog.

## Verdict

The official guide is strong on mechanics: Wrapper integrity, reproducible archives, the configuration
cache, a single version catalog. It says nothing about authority. It never says who may change a build
file or that verification is mandatory, and it admits a catalog doesn't pin resolved versions. The kit's
owner gate fills the first gap for every Gradle build file, Wrapper and `build-logic` included. A project
adapted before the glob set copies it into `config/project.json` (re-running `adopt.sh` keeps an existing
list) before it can claim that agents never touch its build.
