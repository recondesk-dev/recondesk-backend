/** Trigger a direct file download via a temporary anchor (no window.open). */
export function downloadBlobAsFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Wrap raw PDF bytes in a Blob with the correct MIME type for download. */
export function pdfBytesToBlob(pdfBytes: ArrayBuffer): Blob {
  return new Blob([pdfBytes], { type: "application/pdf" });
}
