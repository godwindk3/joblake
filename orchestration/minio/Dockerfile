# Build the official source release: upstream prebuilt images are no longer public.
FROM golang:1.24.8-bookworm AS build
WORKDIR /src/minio

# Release commit: 9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
RUN curl --fail --location --retry 3 \
      https://codeload.github.com/minio/minio/tar.gz/refs/tags/RELEASE.2025-10-15T17-29-55Z \
      --output /tmp/minio.tar.gz \
    && echo 'be6d0bd3696c3a13a35f02d3a0280b64319c67918b4501c5c3d87f96d000085c  /tmp/minio.tar.gz' | sha256sum --check - \
    && tar -xzf /tmp/minio.tar.gz --strip-components=1 \
    && rm /tmp/minio.tar.gz

ENV CGO_ENABLED=0 GOTOOLCHAIN=local
# Set the release metadata explicitly because the verified archive has no .git.
RUN go build -tags kqueue -trimpath -ldflags='-s -w \
      -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z \
      -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z \
      -X github.com/minio/minio/cmd.CommitID=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a \
      -X github.com/minio/minio/cmd.ShortCommitID=9e49d5e7a648 \
      -X github.com/minio/minio/cmd.CopyrightYear=2025' -o /out/minio .

FROM debian:bookworm-slim
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /out/minio /usr/bin/minio
COPY --from=build /src/minio/LICENSE /licenses/LICENSE
COPY --from=build --chmod=755 /src/minio/dockerscripts/docker-entrypoint.sh /usr/bin/docker-entrypoint.sh
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/docker-entrypoint.sh"]
CMD ["minio"]
