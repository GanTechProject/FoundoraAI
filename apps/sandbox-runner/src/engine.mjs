import http from "node:http";
import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";

const MAX_ENGINE_RESPONSE_BYTES = 1_200_000;

export class EngineError extends Error {
  constructor(message, statusCode = 500) {
    super(message);
    this.statusCode = statusCode;
  }
}

function request(
  socketPath,
  method,
  requestPath,
  body = null,
  maximum = MAX_ENGINE_RESPONSE_BYTES,
) {
  return new Promise((resolve, reject) => {
    const encoded = body === null ? null : Buffer.from(JSON.stringify(body));
    const operation = http.request(
      {
        socketPath,
        path: requestPath,
        method,
        headers:
          encoded === null
            ? {}
            : {
                "content-type": "application/json",
                "content-length": encoded.length,
              },
      },
      (response) => {
        const chunks = [];
        let size = 0;
        response.on("data", (chunk) => {
          size += chunk.length;
          if (size > maximum) {
            operation.destroy(
              new EngineError("Docker Engine response exceeded its boundary"),
            );
            return;
          }
          chunks.push(chunk);
        });
        response.on("end", () => {
          const data = Buffer.concat(chunks);
          if (response.statusCode < 200 || response.statusCode >= 300) {
            let detail = data.toString("utf8").slice(0, 500);
            try {
              detail = JSON.parse(detail).message ?? detail;
            } catch {}
            reject(
              new EngineError(
                `Docker Engine ${method} ${requestPath} failed: ${detail}`,
                response.statusCode,
              ),
            );
            return;
          }
          resolve({
            statusCode: response.statusCode,
            headers: response.headers,
            data,
          });
        });
      },
    );
    operation.on("error", reject);
    if (encoded !== null) operation.write(encoded);
    operation.end();
  });
}

function json(response) {
  return JSON.parse(response.data.toString("utf8"));
}

function tarOctal(value, length) {
  return `${value.toString(8).padStart(length - 1, "0")}\0`;
}

function tarName(header, value) {
  if (Buffer.byteLength(value) <= 100) {
    header.write(value, 0, 100, "utf8");
    return;
  }
  const split = value.lastIndexOf("/");
  const prefix = value.slice(0, split);
  const name = value.slice(split + 1);
  if (
    split < 1 ||
    Buffer.byteLength(prefix) > 155 ||
    Buffer.byteLength(name) > 100
  ) {
    throw new EngineError("Validated source path exceeds the archive boundary");
  }
  header.write(name, 0, 100, "utf8");
  header.write(prefix, 345, 155, "utf8");
}

function tarEntry(name, content, mode, type) {
  const header = Buffer.alloc(512);
  tarName(header, name);
  header.write(tarOctal(mode, 8), 100, 8, "ascii");
  header.write(tarOctal(1000, 8), 108, 8, "ascii");
  header.write(tarOctal(1000, 8), 116, 8, "ascii");
  header.write(tarOctal(content.length, 12), 124, 12, "ascii");
  header.write(tarOctal(0, 12), 136, 12, "ascii");
  header.fill(0x20, 148, 156);
  header.write(type, 156, 1, "ascii");
  header.write("ustar\0", 257, 6, "ascii");
  header.write("00", 263, 2, "ascii");
  header.write("pwuser", 265, 32, "ascii");
  header.write("pwuser", 297, 32, "ascii");
  const checksum = header.reduce((sum, byte) => sum + byte, 0);
  header.write(`${checksum.toString(8).padStart(6, "0")}\0 `, 148, 8, "ascii");
  const padding = Buffer.alloc((512 - (content.length % 512)) % 512);
  return Buffer.concat([header, content, padding]);
}

export function buildSourceTar(files, routes) {
  const directories = new Set(["site", "foundora-input"]);
  for (const file of files) {
    const parts = file.path.split("/");
    for (let index = 1; index < parts.length; index += 1) {
      directories.add(`site/${parts.slice(0, index).join("/")}`);
    }
  }
  const entries = [];
  for (const directory of [...directories].sort()) {
    entries.push(tarEntry(`${directory}/`, Buffer.alloc(0), 0o555, "5"));
  }
  for (const file of [...files].sort((left, right) =>
    left.path.localeCompare(right.path),
  )) {
    entries.push(
      tarEntry(
        `site/${file.path}`,
        Buffer.from(file.content, "utf8"),
        0o444,
        "0",
      ),
    );
  }
  entries.push(
    tarEntry(
      "foundora-input/routes.json",
      Buffer.from(JSON.stringify({ contract_version: 1, routes }), "utf8"),
      0o444,
      "0",
    ),
  );
  entries.push(Buffer.alloc(1024));
  return Buffer.concat(entries);
}

function decodeLogs(data) {
  const stdoutHash = createHash("sha256");
  const stderrHash = createHash("sha256");
  const stdout = [];
  const stderr = [];
  let stdoutSize = 0;
  let stderrSize = 0;
  let offset = 0;
  while (offset < data.length) {
    if (offset + 8 > data.length)
      throw new EngineError("Docker log stream header is malformed");
    const stream = data[offset];
    const length = data.readUInt32BE(offset + 4);
    offset += 8;
    if (offset + length > data.length)
      throw new EngineError("Docker log stream frame is malformed");
    const content = data.subarray(offset, offset + length);
    offset += length;
    const target = stream === 2 ? stderr : stdout;
    const hash = stream === 2 ? stderrHash : stdoutHash;
    const current = stream === 2 ? stderrSize : stdoutSize;
    hash.update(content);
    if (current < 65_536) target.push(content.subarray(0, 65_536 - current));
    if (stream === 2) stderrSize += content.length;
    else stdoutSize += content.length;
  }
  return {
    stdout: Buffer.concat(stdout).toString("utf8"),
    stderr: Buffer.concat(stderr).toString("utf8"),
    stdout_sha256: stdoutHash.digest("hex"),
    stderr_sha256: stderrHash.digest("hex"),
    combined_bytes: stdoutSize + stderrSize,
  };
}

export class DockerEngine {
  constructor({ socketPath, seccompProfile, seccompSha256, runtimeImage }) {
    this.socketPath = socketPath;
    this.seccompProfile = seccompProfile;
    this.seccompSha256 = seccompSha256;
    this.runtimeImage = runtimeImage;
  }

  async ping() {
    const response = await request(this.socketPath, "GET", "/_ping", null, 64);
    if (response.data.toString("utf8") !== "OK")
      throw new EngineError("Docker Engine ping failed");
  }

  async resolveRuntime() {
    const image = json(
      await request(
        this.socketPath,
        "GET",
        `/images/${encodeURIComponent(this.runtimeImage)}/json`,
      ),
    );
    const labels = image.Config?.Labels ?? {};
    if (
      !/^sha256:[a-f0-9]{64}$/.test(image.Id) ||
      labels["org.foundora.sandbox.profile"] !== "static-website@1" ||
      labels["org.foundora.sandbox.harness-contract"] !== "1" ||
      labels["org.foundora.sandbox.build-manifest-sha256"] !==
        "ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601" ||
      image.Config?.User !== "pwuser" ||
      JSON.stringify(image.Config?.Entrypoint) !==
        JSON.stringify(["node", "/opt/foundora/runtime/runtime.mjs"])
    ) {
      throw new EngineError("Runtime image does not match static-website@1");
    }
    return image.Id;
  }

  async prepareSource(executionId, imageId, files, routes) {
    const volumeName = `foundora-sandbox-source-${executionId}`;
    await request(this.socketPath, "POST", "/volumes/create", {
      Name: volumeName,
      Driver: "local",
      Labels: {
        "foundora.sandbox.managed": "true",
        "foundora.sandbox.execution": executionId,
        "foundora.sandbox.resource": "source",
      },
    });
    const helper = json(
      await request(
        this.socketPath,
        "POST",
        `/containers/create?name=${encodeURIComponent(`foundora-sandbox-source-${executionId}`)}`,
        {
          Image: imageId,
          Entrypoint: ["/bin/true"],
          Labels: {
            "foundora.sandbox.managed": "true",
            "foundora.sandbox.execution": executionId,
            "foundora.sandbox.resource": "source-populator",
          },
          HostConfig: {
            AutoRemove: false,
            CapDrop: ["ALL"],
            Mounts: [
              {
                Type: "volume",
                Source: volumeName,
                Target: "/bundle",
                ReadOnly: false,
              },
            ],
            NetworkMode: "none",
            Privileged: false,
            SecurityOpt: ["no-new-privileges:true"],
          },
        },
      ),
    );
    try {
      await this.copyArchive(
        helper.Id,
        "/bundle",
        buildSourceTar(files, routes),
      );
    } finally {
      await this.removeContainer(helper.Id);
    }
    return volumeName;
  }

  async create(executionId, requestDigest, imageId, volumeName) {
    const name = `foundora-sandbox-${executionId}`;
    const specification = {
      Image: imageId,
      User: "pwuser",
      Env: ["HOME=/home/pwuser", "NODE_ENV=production"],
      Labels: {
        "foundora.sandbox.managed": "true",
        "foundora.sandbox.execution": executionId,
        "foundora.sandbox.request-digest": requestDigest,
        "foundora.sandbox.profile": "static-website@1",
      },
      StopTimeout: 3,
      HostConfig: {
        AutoRemove: false,
        Binds: [],
        CapAdd: ["SYS_CHROOT"],
        CapDrop: ["ALL"],
        Devices: [],
        Init: true,
        LogConfig: {
          Type: "local",
          Config: { compress: "false", "max-file": "1", "max-size": "1m" },
        },
        Mounts: [
          {
            Type: "volume",
            Source: volumeName,
            Target: "/site",
            ReadOnly: true,
            VolumeOptions: { Subpath: "site" },
          },
          {
            Type: "volume",
            Source: volumeName,
            Target: "/foundora-input",
            ReadOnly: true,
            VolumeOptions: { Subpath: "foundora-input" },
          },
        ],
        Memory: 536_870_912,
        MemorySwap: 536_870_912,
        NanoCpus: 1_000_000_000,
        NetworkMode: "none",
        PidsLimit: 128,
        Privileged: false,
        PublishAllPorts: false,
        ReadonlyRootfs: true,
        SecurityOpt: [
          "no-new-privileges:true",
          `seccomp=${this.seccompProfile}`,
        ],
        ShmSize: 134_217_728,
        Tmpfs: {
          "/dev/shm": "rw,noexec,nosuid,nodev,size=134217728",
          "/tmp": "rw,noexec,nosuid,nodev,size=134217728",
        },
      },
    };
    const response = json(
      await request(
        this.socketPath,
        "POST",
        `/containers/create?name=${encodeURIComponent(name)}`,
        specification,
      ),
    );
    return { id: response.Id, name };
  }

  async copyArchive(containerId, destination, archive) {
    await new Promise((resolve, reject) => {
      const operation = http.request(
        {
          socketPath: this.socketPath,
          path: `/containers/${containerId}/archive?path=${encodeURIComponent(destination)}`,
          method: "PUT",
          headers: {
            "content-type": "application/x-tar",
            "content-length": archive.length,
          },
        },
        (response) => {
          const chunks = [];
          response.on("data", (chunk) => chunks.push(chunk));
          response.on("end", () => {
            if (response.statusCode < 200 || response.statusCode >= 300) {
              reject(
                new EngineError(
                  `Docker source copy failed: ${Buffer.concat(chunks).toString("utf8").slice(0, 500)}`,
                ),
              );
            } else resolve();
          });
        },
      );
      operation.on("error", reject);
      operation.end(archive);
    });
  }

  async inspect(containerId) {
    return json(
      await request(this.socketPath, "GET", `/containers/${containerId}/json`),
    );
  }

  validateControls(container, imageId, volumeName) {
    const host = container.HostConfig;
    const security = host.SecurityOpt ?? [];
    const capAdd = host.CapAdd ?? [];
    const capDrop = host.CapDrop ?? [];
    const environment = container.Config.Env ?? [];
    const forbiddenEnvironment = environment.some((entry) =>
      /^(OPENAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|FOUNDORA_DATABASE_URL|FOUNDORA_REDIS_URL|FOUNDORA_SANDBOX_RUNNER_TOKEN)=/.test(
        entry,
      ),
    );
    const noHostNamespaces =
      !host.PidMode && host.IpcMode !== "host" && host.UTSMode !== "host";
    const sourceMounts = container.Mounts ?? [];
    const configuredMounts = host.Mounts ?? [];
    const expectedMounts = new Map([
      ["/site", "site"],
      ["/foundora-input", "foundora-input"],
    ]);
    const labels = container.Config.Labels ?? {};
    if (
      container.Config.Image !== imageId ||
      container.Config.User !== "pwuser" ||
      JSON.stringify(container.Config.Entrypoint) !==
        JSON.stringify(["node", "/opt/foundora/runtime/runtime.mjs"]) ||
      container.Config.StopTimeout !== 3 ||
      !environment.includes("HOME=/home/pwuser") ||
      !environment.includes("NODE_ENV=production") ||
      forbiddenEnvironment ||
      labels["foundora.sandbox.managed"] !== "true" ||
      labels["foundora.sandbox.profile"] !== "static-website@1" ||
      host.NanoCpus !== 1_000_000_000 ||
      host.Memory !== 536_870_912 ||
      host.MemorySwap !== 536_870_912 ||
      host.PidsLimit !== 128 ||
      host.NetworkMode !== "none" ||
      host.Init !== true ||
      host.ReadonlyRootfs !== true ||
      host.Privileged !== false ||
      host.PublishAllPorts !== false ||
      !capDrop.includes("ALL") ||
      capAdd.length !== 1 ||
      capAdd[0] !== "SYS_CHROOT" ||
      capAdd.includes("SYS_ADMIN") ||
      !security.includes("no-new-privileges:true") ||
      !security.includes(`seccomp=${this.seccompProfile}`) ||
      (host.Devices ?? []).length !== 0 ||
      (host.Binds ?? []).length !== 0 ||
      (host.DeviceRequests ?? []).length !== 0 ||
      (host.Links ?? []).length !== 0 ||
      (host.VolumesFrom ?? []).length !== 0 ||
      Object.keys(host.PortBindings ?? {}).length !== 0 ||
      Object.keys(container.Config.ExposedPorts ?? {}).length !== 0 ||
      sourceMounts.length !== 2 ||
      configuredMounts.length !== 2 ||
      sourceMounts.some(
        (mount) =>
          mount.Type !== "volume" ||
          mount.Name !== volumeName ||
          mount.RW !== false ||
          !expectedMounts.has(mount.Destination),
      ) ||
      configuredMounts.some(
        (mount) =>
          mount.Type !== "volume" ||
          mount.Source !== volumeName ||
          mount.ReadOnly !== true ||
          mount.VolumeOptions?.Subpath !== expectedMounts.get(mount.Target),
      ) ||
      !noHostNamespaces ||
      host.ShmSize !== 134_217_728 ||
      host.LogConfig?.Type !== "local" ||
      host.LogConfig?.Config?.compress !== "false" ||
      host.LogConfig?.Config?.["max-file"] !== "1" ||
      host.LogConfig?.Config?.["max-size"] !== "1m" ||
      host.Tmpfs?.["/tmp"] !== "rw,noexec,nosuid,nodev,size=134217728" ||
      host.Tmpfs?.["/dev/shm"] !== "rw,noexec,nosuid,nodev,size=134217728"
    ) {
      throw new EngineError(
        "Created child does not match static-website@1 controls",
      );
    }
    return {
      cpu_nanos: host.NanoCpus,
      memory_bytes: host.Memory,
      memory_swap_bytes: host.MemorySwap,
      pids_limit: host.PidsLimit,
      wall_timeout_seconds: 60,
      termination_grace_seconds: 3,
      tmpfs_bytes: 134_217_728,
      dev_shm_bytes: 134_217_728,
      combined_output_bytes: 1_048_576,
      network_mode: "none",
      read_only_root_filesystem: true,
      source_read_only: true,
      run_as_non_root: true,
      drop_all_capabilities: true,
      add_sys_chroot_capability: true,
      no_new_privileges: true,
      no_host_namespaces: true,
      no_devices: true,
      seccomp_profile_sha256: this.seccompSha256,
    };
  }

  async start(containerId) {
    await request(
      this.socketPath,
      "POST",
      `/containers/${containerId}/start`,
      {},
    );
  }

  async wait(containerId) {
    return json(
      await request(
        this.socketPath,
        "POST",
        `/containers/${containerId}/wait?condition=not-running`,
        {},
        4096,
      ),
    ).StatusCode;
  }

  async stop(containerId) {
    try {
      await request(
        this.socketPath,
        "POST",
        `/containers/${containerId}/stop?t=3`,
        {},
      );
    } catch (error) {
      if (
        !(error instanceof EngineError) ||
        ![304, 404].includes(error.statusCode)
      )
        throw error;
    }
  }

  async logs(containerId) {
    const response = await request(
      this.socketPath,
      "GET",
      `/containers/${containerId}/logs?stdout=1&stderr=1&timestamps=0`,
    );
    const logs = decodeLogs(response.data);
    if (logs.combined_bytes > 1_048_576) {
      throw new EngineError("Child output exceeded static-website@1");
    }
    return logs;
  }

  async removeContainer(containerId) {
    try {
      await request(
        this.socketPath,
        "DELETE",
        `/containers/${containerId}?force=1&v=1`,
      );
    } catch (error) {
      if (!(error instanceof EngineError) || error.statusCode !== 404)
        throw error;
    }
  }

  async removeVolume(volumeName) {
    try {
      await request(
        this.socketPath,
        "DELETE",
        `/volumes/${encodeURIComponent(volumeName)}?force=1`,
      );
    } catch (error) {
      if (!(error instanceof EngineError) || error.statusCode !== 404)
        throw error;
    }
  }

  async listManaged(executionId = null) {
    const labels = ["foundora.sandbox.managed=true"];
    if (executionId !== null)
      labels.push(`foundora.sandbox.execution=${executionId}`);
    const filters = encodeURIComponent(JSON.stringify({ label: labels }));
    const containers = json(
      await request(
        this.socketPath,
        "GET",
        `/containers/json?all=1&filters=${filters}`,
      ),
    ).map((item) => ({ ...item, resourceType: "container" }));
    const volumes =
      json(await request(this.socketPath, "GET", `/volumes?filters=${filters}`))
        .Volumes ?? [];
    return [
      ...containers,
      ...volumes.map((item) => ({
        ...item,
        Id: item.Name,
        resourceType: "volume",
      })),
    ];
  }

  async removeResource(resource) {
    if (resource.resourceType === "volume")
      await this.removeVolume(resource.Id);
    else await this.removeContainer(resource.Id);
  }
}
