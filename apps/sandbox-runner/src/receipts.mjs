import fs from "node:fs/promises";
import path from "node:path";

export class ReceiptStore {
  constructor(root) {
    this.root = root;
  }

  async initialize() {
    await fs.mkdir(this.root, { recursive: true, mode: 0o700 });
  }

  file(executionId) {
    return path.join(this.root, `${executionId}.json`);
  }

  async read(executionId) {
    try {
      return JSON.parse(await fs.readFile(this.file(executionId), "utf8"));
    } catch (error) {
      if (error.code === "ENOENT") return null;
      throw error;
    }
  }

  async write(receipt) {
    const destination = this.file(receipt.execution_id);
    const temporary = `${destination}.${process.pid}.${Date.now()}.tmp`;
    const handle = await fs.open(temporary, "wx", 0o600);
    try {
      await handle.writeFile(`${JSON.stringify(receipt)}\n`, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.rename(temporary, destination);
    const directory = await fs.open(this.root, "r");
    try {
      await directory.sync();
    } finally {
      await directory.close();
    }
  }

  async list() {
    const names = await fs.readdir(this.root);
    const receipts = [];
    for (const name of names.filter((item) => item.endsWith(".json")).sort()) {
      receipts.push(
        JSON.parse(await fs.readFile(path.join(this.root, name), "utf8")),
      );
    }
    return receipts;
  }
}
