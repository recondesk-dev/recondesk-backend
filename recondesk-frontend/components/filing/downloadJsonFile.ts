/**
 * Download a JavaScript object as a formatted JSON file in the browser.
 */
export function downloadJsonFile(filename: string, data: unknown): void {
  try {
    const jsonStr = typeof data === "string" ? data : JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("Failed to download JSON file:", err);
  }
}
