# syntax=docker/dockerfile:1
# Only public distribution/dependency cache is accepted, never the whole GRADLE_USER_HOME.
FROM eclipse-temurin:21-jdk-jammy
ARG CACHE_SEED_NONCE
RUN --mount=type=bind,from=gradle-wrapper-cache,target=/seed-wrapper \
    --mount=type=bind,from=gradle-module-cache,target=/seed-modules \
    --mount=type=cache,id=metor-gradle,target=/root/.gradle,sharing=locked \
    test -n "$CACHE_SEED_NONCE" \
    && mkdir -p /root/.gradle/wrapper/dists/gradle-8.14-bin/38aieal9i53h9rfe7vjup95b9 /root/.gradle/caches/modules-2 \
    && cp -R /seed-wrapper/gradle-8.14 /root/.gradle/wrapper/dists/gradle-8.14-bin/38aieal9i53h9rfe7vjup95b9/ \
    && cp /seed-wrapper/gradle-8.14-bin.zip.ok /root/.gradle/wrapper/dists/gradle-8.14-bin/38aieal9i53h9rfe7vjup95b9/ \
    && cp -R /seed-modules/files-2.1 /root/.gradle/caches/modules-2/ \
    && cp -R /seed-modules/metadata-* /root/.gradle/caches/modules-2/
