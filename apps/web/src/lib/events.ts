export type Frame = { id?: number; event: string; data: string };
export class SSEDecoder {
  private buffer = "";
  push(text: string): Frame[] {
    this.buffer += text;
    if (this.buffer.length > 524288) throw new Error("Event frame too large");
    const frames: Frame[] = [];
    while (true) {
      const boundary = this.buffer.match(/\r?\n\r?\n/);
      if (!boundary || boundary.index === undefined) break;
      const block = this.buffer.slice(0, boundary.index);
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length);
      let event = "message";
      let identity: number | undefined;
      const data: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("id:")) {
          const value = line.slice(3).trim();
          if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)))
            throw new Error("Invalid cursor");
          identity = Number(value);
        }
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:"))
          data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length)
        frames.push({ id: identity, event, data: data.join("\n") });
    }
    return frames;
  }
}
export function eventDecision(
  frame: Frame,
  cursor: number,
): "skip" | "refresh" | "resync" {
  if (frame.event === "stream.error") return "resync";
  const data = JSON.parse(frame.data);
  if (frame.id === undefined || data.experiment_seq !== frame.id)
    throw new Error("Mismatched event");
  if (frame.id <= cursor) return "skip";
  return frame.id === cursor + 1 ? "refresh" : "resync";
}
