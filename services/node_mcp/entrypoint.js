#!/usr/bin/env node
/**
 * Launch each stdio MCP package behind Supergateway (Streamable HTTP).
 *
 * Config: servers.json
 *   { "servers": [{ "slug", "port", "command", "args"? }] }
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = __dirname;
const binDir = path.join(root, "node_modules", ".bin");
const configPath = path.join(root, "servers.json");
const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
const servers = Array.isArray(config.servers) ? config.servers : [];

if (servers.length === 0) {
  console.error("No servers configured in servers.json");
  process.exit(1);
}

const env = {
  ...process.env,
  PATH: `${binDir}${path.delimiter}${process.env.PATH || ""}`,
};

const children = [];

function stdioCommand(server) {
  const args = Array.isArray(server.args) ? server.args : [];
  const parts = [server.command, ...args].map(String);
  return parts
    .map((p) => (/\s/.test(p) ? JSON.stringify(p) : p))
    .join(" ");
}

function startServer(server) {
  const port = Number(server.port);
  if (!Number.isFinite(port)) {
    throw new Error(`Server ${server.slug} missing numeric port`);
  }
  const cmd = stdioCommand(server);
  const gatewayBin = path.join(binDir, "supergateway");
  const args = [
    "--stdio",
    cmd,
    "--outputTransport",
    "streamableHttp",
    "--port",
    String(port),
    "--streamableHttpPath",
    "/mcp",
    "--healthEndpoint",
    "/health",
    "--logLevel",
    "info",
  ];
  console.log(`[node-mcp] starting ${server.slug} on :${port} → ${cmd}`);
  const child = spawn(gatewayBin, args, {
    stdio: "inherit",
    env,
  });
  child.on("exit", (code, signal) => {
    console.error(
      `[node-mcp] ${server.slug} exited code=${code} signal=${signal}`
    );
    process.exit(code ?? 1);
  });
  children.push(child);
}

for (const server of servers) {
  startServer(server);
}

function shutdown(signal) {
  console.log(`[node-mcp] received ${signal}, stopping…`);
  for (const child of children) {
    child.kill("SIGTERM");
  }
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
