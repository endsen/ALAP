export class APIError extends Error {
  constructor(
    public code: string,
    public status: number,
    public requestId = "",
  ) {
    super(code);
    this.name = "APIError";
  }
}
export const explain = (e: unknown): string => {
  if (!(e instanceof APIError))
    return "连接中断。请核对当前状态；提交结果可能尚未确认。";
  if (e.status === 401) return "会话已失效，请重新登录。";
  if (e.status === 403) return "你没有此资源或操作的权限。";
  if (e.code === "EXECUTION_UNKNOWN")
    return "请求结果尚不明确。请刷新核对，勿重复提交。";
  if (e.code === "ARTIFACT_INVALID")
    return "数据文件缺失、损坏或校验不一致，暂时无法查看或下载。请联系管理员核查数据完整性，处理后重新获取状态。";
  if (e.status === 409) return "版本或状态已变化。请刷新，查看差异后重新确认。";
  if (e.status === 429) return "请求较频繁，请稍后再试。";
  if (e.status === 422)
    return `请求未通过校验（${e.code}）。请检查计划或输入。`;
  if (e.status === 404) return "资源不存在或已不可访问。";
  return `服务暂时不可用（${e.code}）。`;
};
export class Client {
  private keys = new Map<string, string>();
  private uncertain = new Map<string, string>();
  constructor(
    private token: string,
    private expired: () => void,
  ) {}
  invalidate() {
    this.expired();
  }
  headers() {
    return { Authorization: `Bearer ${this.token}` };
  }
  async read<T>(path: string, signal?: AbortSignal): Promise<T> {
    return this.parse<T>(
      await fetch(`/api/v1${path}`, {
        headers: this.headers(),
        cache: "no-store",
        signal,
      }),
    );
  }
  private async parse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      if (response.status === 401) this.expired();
      if (response.status === 403 && typeof window !== "undefined")
        window.dispatchEvent(new Event("alap:access-denied"));
      throw new APIError(
        body.error?.code || "SERVICE_UNAVAILABLE",
        response.status,
        body.error?.request_id || "",
      );
    }
    return response.json() as Promise<T>;
  }
  async mutate<T>(
    path: string,
    body?: unknown,
    revision?: number,
    method = "POST",
  ): Promise<T> {
    const fingerprint = JSON.stringify([method, path, body, revision]);
    const operation = method + ":" + path;
    if (
      this.uncertain.has(operation) &&
      this.uncertain.get(operation) !== fingerprint
    )
      throw new APIError("EXECUTION_UNKNOWN", 409);
    const key = this.keys.get(fingerprint) || crypto.randomUUID();
    this.keys.set(fingerprint, key);
    const headers: Record<string, string> = {
      ...this.headers(),
      "Idempotency-Key": key,
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (revision !== undefined) headers["If-Match"] = `"${revision}"`;
    try {
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(120000),
      });
      const value = await this.parse<T>(response);
      this.keys.delete(fingerprint);
      this.uncertain.delete(operation);
      return value;
    } catch (e) {
      // Keep the same key after ambiguous delivery; never silently regenerate a request.
      if (
        e instanceof APIError &&
        e.status < 500 &&
        e.code !== "EXECUTION_UNKNOWN"
      ) {
        this.keys.delete(fingerprint);
        this.uncertain.delete(operation);
      } else this.uncertain.set(operation, fingerprint);
      throw e;
    }
  }
  async download(path: string, filename: string) {
    const response = await fetch(`/api/v1${path}`, {
      headers: this.headers(),
      cache: "no-store",
    });
    if (!response.ok) {
      await this.parse(response);
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
export const id = (value: string) => encodeURIComponent(value);
